"""Generate, preserve drafts, verify guidance and repair at most twice."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Callable

from legacylift.runtimes.python_target import CandidateRejected

from . import model_profiles
from .call_ledger import CallBudgetExceeded, CallLedger
from .contracts import canonical_hash
from .format_recovery import POLICY as FORMAT_RECOVERY_POLICY
from .format_recovery import recover_fstring_indices
from .generation import (
    GeneratedMigration,
    GeneratedRangeRepair,
    GeneratedRepair,
    PromptBudgetExceeded,
    ProviderFailure,
    apply_source_edits,
    apply_source_ranges,
    bind_read_stage_evidence,
    build_context,
    generate,
    normalize_read_body,
    prepare_prompt,
    read_stage_prompt,
    supplied_evidence_ids,
)
from .scaffold import (
    candidate_scaffold,
    create_interface_findings,
    fragment_is_evidence_echo,
    model_fragment,
    source_assembly_metadata,
)
from .security import review_target_source as review_source
from .study import evaluate_source, write_json


def can_resume_prompt_rebuild(directory: Path, failure: dict) -> bool:
    """Allow an explicit local rebuild only when a saved draft preceded the rejection."""
    attempt = failure.get("attempt")
    eligible = (
        failure.get("category") == "prompt_too_large"
        and isinstance(attempt, int)
        and not isinstance(attempt, bool)
        and attempt > 0
        and (directory / f"draft-{attempt - 1}.py").is_file()
        and not (directory / f"call-{attempt}.json").exists()
    )
    if not eligible:
        return False
    budget = CallLedger(directory.parent.parent).summary_for_run(directory.name)
    return budget is None or budget["remaining"] > 0


def _feedback_for_next_attempt(previous: dict | None, evaluation: dict) -> dict:
    """Keep guidance mismatches available when static review blocks a repair patch."""
    if any(
        result.get("split", "guidance") != "guidance" for result in evaluation.get("results", [])
    ):
        raise ValueError("repair feedback must contain guidance results only")
    current = {
        key: value
        for key, value in evaluation.items()
        if key in {"status", "detail", "review", "passed_count", "scenario_count", "diagnostics"}
    }
    error_counts = {}
    for observation in evaluation.get("observations", []):
        if observation.get("split") != "guidance":
            continue
        for index, step in enumerate(observation.get("steps", [])):
            body = step.get("response", {}).get("json")
            errors = body.get("errors") if isinstance(body, dict) else None
            if isinstance(errors, list) and all(isinstance(error, str) for error in errors):
                path = f"steps[{index}].response.json.errors.length"
                error_counts[(observation["scenario_id"], path)] = (len(errors), len(set(errors)))
    current_mismatches = []
    for result in [r for r in evaluation.get("results", []) if not r.get("passed")][:6]:
        mismatches = []
        for mismatch in result.get("mismatches", [])[:8]:
            row = dict(mismatch)
            counts = error_counts.get((result.get("scenario_id"), row.get("path")))
            if counts and row.get("actual") == counts[0] and counts[1] < counts[0]:
                row["observed_distinct_errors"] = counts[1]
            mismatches.append(row)
        current_mismatches.append({**result, "mismatches": mismatches})
    current["mismatches"] = current_mismatches
    preserved = set((previous or {}).get("preserve_passed_guidance_cases", []))
    preserved.difference_update(
        result.get("scenario_id")
        for result in evaluation.get("results", [])
        if not result.get("passed")
    )
    preserved.update(
        result["scenario_id"]
        for result in evaluation.get("results", [])
        if result.get("passed") and result.get("scenario_id")
    )
    if preserved:
        current["preserve_passed_guidance_cases"] = sorted(preserved)

    if previous and evaluation.get("status") == "static_review_blocked":
        merged = {**previous, **current}
        if not current_mismatches:
            merged["mismatches"] = previous.get("mismatches", [])
        if not evaluation.get("diagnostics"):
            merged["diagnostics"] = previous.get("diagnostics", "")
        finding_messages = [
            str(item.get("message", item.get("rule", "static review blocked")))
            for item in evaluation.get("review", {}).get("findings", [])
            if isinstance(item, dict)
        ]
        merged["detail"] = "Repair was blocked: " + "; ".join(finding_messages[:3])
        merged["detail"] += ". Preserve and fix the guidance failures shown below."
        return merged
    return current


def _prepare_seed_candidate(
    workspace: Path, directory: Path, context: dict, seed_run_id: str
) -> dict:
    if not seed_run_id.isalnum():
        raise ValueError("invalid seed run identifier")
    seed_metadata_path = directory / "seed.json"
    draft_path = directory / "draft-0.py"
    draft_record_path = directory / "draft-0.json"
    if seed_metadata_path.exists():
        metadata = json.loads(seed_metadata_path.read_text(encoding="utf-8"))
        if metadata.get("source_run_id") != seed_run_id:
            raise ValueError("seed run identifier is immutable")
        if metadata.get("context_sha256") != canonical_hash(context):
            raise ValueError("seed evidence context differs from the new run")
        if not draft_path.is_file() or not draft_record_path.is_file():
            raise ValueError("seeded candidate files are incomplete")
        source = draft_path.read_text(encoding="utf-8")
        if canonical_hash(source) != metadata.get("source_sha256"):
            raise ValueError("seeded candidate checksum differs")
        return metadata
    if draft_path.exists() or draft_record_path.exists():
        raise ValueError("cannot seed over an existing draft")

    source_directory = workspace / "runs" / seed_run_id
    source_result_path = source_directory / "result.json"
    source_code_path = source_directory / "app.py"
    if not source_result_path.is_file():
        raise ValueError("seed run has no saved result")
    source_result = json.loads(source_result_path.read_text(encoding="utf-8"))
    if (
        source_result.get("held_out_evaluated")
        or source_result.get("human_approved")
        or (source_directory / "held-out.json").is_file()
    ):
        raise ValueError("held-out or approved runs cannot be used as repair seeds")
    allowed_statuses = {
        "static_review_blocked",
        "compatibility_failed",
        "candidate_boot_failed",
        "provider_paused",
        "provider_failed",
    }
    if source_result.get("status") not in allowed_statuses:
        raise ValueError("only unevaluated or guidance-failing candidate runs may be seeded")
    if source_result.get("workflow") != context.get("workflow"):
        raise ValueError("seed workflow differs from the new run")
    if source_result.get("condition") != context.get("condition"):
        raise ValueError("seed evidence condition differs from the new run")
    if source_result.get("context_sha256") != canonical_hash(context):
        raise ValueError("seed evidence context differs from the new run")
    attempts = source_result.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        raise ValueError("seed run has no completed candidate attempt")
    source_attempt = attempts[-1]
    attempt_path = source_directory / f"draft-{source_attempt.get('attempt')}.py"
    if attempt_path.is_file():
        source_code_path = attempt_path
    if not source_code_path.is_file():
        raise ValueError("seed run has no saved candidate source")
    source = source_code_path.read_text(encoding="utf-8")
    source_hash = canonical_hash(source)
    if source_hash != source_attempt.get("source_sha256"):
        raise ValueError("seed candidate checksum differs from its run record")
    scaffold = candidate_scaffold(context)
    assembly = {}
    if scaffold:
        fragment = model_fragment(source, scaffold)
        assembly = source_assembly_metadata(scaffold, fragment)
        if source_attempt.get("source_assembly") != assembly:
            raise ValueError("seed candidate assembly differs from its run record")
        (directory / "fragment-0.py").write_text(fragment, encoding="utf-8")
    source_provenance = source_attempt.get("provenance", {})
    metadata = {
        "source_run_id": seed_run_id,
        "source_attempt": source_attempt.get("attempt"),
        "source_sha256": source_hash,
        "context_sha256": canonical_hash(context),
        "held_out_evaluated": False,
    }
    draft_path.write_text(source, encoding="utf-8")
    write_json(
        draft_record_path,
        {
            "attempt": 0,
            "summary": source_attempt.get("summary", "Seeded candidate"),
            "unknowns": source_attempt.get("unknowns", []),
            "evidence_ids": source_attempt.get("evidence_ids", []),
            "source_sha256": source_hash,
            **({"source_assembly": assembly} if assembly else {}),
            "review": review_source(source),
            "provenance": {
                "seeded": True,
                "source_run_id": seed_run_id,
                "source_attempt": source_attempt.get("attempt"),
                "source_provider": source_provenance.get("provider"),
                "source_model": source_provenance.get("model"),
                "source_sha256": source_hash,
            },
        },
    )
    write_json(seed_metadata_path, metadata)
    return metadata


def _generate_read_stages(
    context,
    prompt,
    directory,
    workspace,
    provider,
    ledger,
    reservations,
    before_request,
    checkpoint,
):
    """Cache each bounded provider response before assembling the two model handlers."""
    records = []
    context_hash = canonical_hash(context)
    stages = (
        ("read_issue", "read_issue(api_key, issue_id, include)"),
        ("create_issue", "create_issue(api_key, payload, base_url)"),
    )
    # Reject an oversized later stage before spending a request on the first one.
    prepared_stages = [
        (handler, signature, read_stage_prompt(context, handler)) for handler, signature in stages
    ]
    for handler, signature, stage_prompt in prepared_stages:
        path = directory / f"stage-{handler}.json"
        if path.exists():
            record = json.loads(path.read_text(encoding="utf-8"))
            if (
                record.get("context_sha256") != context_hash
                or record.get("prompt_sha256") != canonical_hash(stage_prompt)
                or record.get("handler") != handler
                or record.get("signature") != signature
                or canonical_hash(record["draft"]["source"]) != record.get("source_sha256")
            ):
                raise ValueError("saved read stage differs from its context, prompt or source")
            metadata = record["provenance"]
            request_ids = metadata.get("request_reservations")
            if (
                not isinstance(request_ids, list)
                or not request_ids
                or any(type(value) is not int for value in request_ids)
                or len(request_ids) != len(set(request_ids))
            ):
                raise ValueError("saved read stage has invalid request reservations")
            summary = ledger.summary_for_run(directory.name) or {}
            requests = {item["request_id"]: item for item in summary.get("requests", [])}
            if (
                metadata.get("provider") != provider
                or metadata.get("prompt_sha256") != canonical_hash(stage_prompt)
                or any(
                    value not in requests
                    or requests[value]["run_id"] != directory.name
                    or requests[value]["attempt"] != 0
                    or requests[value]["provider"] != provider
                    or requests[value]["model"] != metadata.get("model")
                    or requests[value]["prompt_sha256"] != canonical_hash(stage_prompt)
                    for value in request_ids
                )
            ):
                raise ValueError("saved read stage provenance differs from its request ledger")
            ledger.finish(
                [(value, metadata["provider"]) for value in metadata["request_reservations"]],
                metadata.get("attempts", []),
            )
        else:
            pacing = workspace / "provider-last-call.json"
            last = json.loads(pacing.read_text()) if pacing.exists() else {"at": 0}
            while time.time() - last["at"] < 65:
                checkpoint("Waiting for the next staged read request", 0.0)
                time.sleep(1)
            write_json(pacing, {"at": time.time()})
            checkpoint(f"Generating {handler} body", 0.0)
            draft, metadata = generate(
                stage_prompt,
                provider=provider,
                response_format="handler_body",
                groq_reasoning_effort=context.get("groq_reasoning_effort"),
                before_request=lambda name, model: before_request(
                    name, model, request_prompt=stage_prompt
                ),
            )
            metadata["request_reservations"] = [value for value, _ in reservations]
            if context.get("read_format_recovery") == FORMAT_RECOVERY_POLICY:
                normalized, recovery = recover_fstring_indices(draft.source)
                if recovery is not None:
                    metadata["format_recovery"] = [recovery]
                    draft = draft.model_copy(update={"source": normalized})
            normalized, recovery = normalize_read_body(handler, draft.source)
            if recovery is not None:
                metadata["body_normalization"] = recovery
                draft = draft.model_copy(update={"source": normalized})
            record = {
                "handler": handler,
                "signature": signature,
                "context_sha256": context_hash,
                "prompt_sha256": canonical_hash(stage_prompt),
                "draft": draft.model_dump(),
                "source_sha256": canonical_hash(draft.source),
                "provenance": metadata,
            }
            with path.open("x", encoding="utf-8") as output:
                json.dump(record, output, indent=2)
            ledger.finish(reservations, metadata.get("attempts", []))
            reservations.clear()
        records.append(record)
    source = (
        "\n".join(
            f"def {record['signature']}:\n"
            + "\n".join(
                "    " + line if line else "" for line in record["draft"]["source"].splitlines()
            )
            for record in records
        )
        + "\n"
    )
    metadata = records[0]["provenance"]
    stages = [record["provenance"] for record in records]
    usage = {
        key: sum(stage["usage"][key] for stage in stages)
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "promptTokenCount",
            "candidatesTokenCount",
            "totalTokenCount",
        )
        if all(type(stage.get("usage", {}).get(key)) is int for stage in stages)
    }
    return GeneratedMigration(
        summary="Staged read and create bodies with reviewed update support",
        evidence_ids=sorted(
            {value for record in records for value in record["draft"]["evidence_ids"]}
        ),
        unknowns=list(
            dict.fromkeys(value for record in records for value in record["draft"]["unknowns"])
        ),
        source=source,
    ), {
        "provider": metadata["provider"],
        "model": metadata["model"],
        "prompt_sha256": canonical_hash(prompt),
        "usage": usage,
        "latency_seconds": sum(stage.get("latency_seconds", 0) for stage in stages),
        "attempts": [item for stage in stages for item in stage.get("attempts", [])],
        "request_reservations": [
            value for stage in stages for value in stage["request_reservations"]
        ],
        "implementation_protocol": "read-" + context["read_generation_strategy"],
        "staged_generation": [
            {"file": f"stage-{record['handler']}.json", "sha256": canonical_hash(record)}
            for record in records
        ],
    }


def migrate(
    workspace: Path,
    *,
    workflow="read",
    condition="hybrid",
    provider: str | None = None,
    max_repairs=2,
    checkpoint: Callable = lambda *args: None,
    run_id=None,
    retry_failed_call=False,
    seed_run_id=None,
    staged_read=False,
    groq_reasoning_effort=None,
) -> dict:
    if max_repairs not in {0, 1, 2}:
        raise ValueError("repairs must be between zero and two")
    if groq_reasoning_effort not in {None, "low", "medium", "high"}:
        raise ValueError("unsupported Groq reasoning effort")
    if groq_reasoning_effort is not None and not staged_read:
        raise ValueError("explicit reasoning selection requires staged read")
    run_id = run_id or uuid.uuid4().hex
    if not run_id.isalnum():
        raise ValueError("invalid run identifier")
    if seed_run_id is not None and (not seed_run_id.isalnum() or seed_run_id == run_id):
        raise ValueError("invalid seed run identifier")
    directory = workspace / "runs" / run_id
    directory.mkdir(parents=True, exist_ok=True)
    saved_result_path = directory / "result.json"
    saved_result = None
    if saved_result_path.exists():
        saved_result = json.loads(saved_result_path.read_text(encoding="utf-8"))
        saved_provider = saved_result.get("provider_policy")
        if provider is None:
            provider = saved_provider or "auto"
        elif saved_provider and provider != saved_provider:
            raise ValueError(
                "Run provider policy is immutable; start a new seeded trial to switch providers"
            )
        if saved_result.get("workflow") != workflow or saved_result.get("condition") != condition:
            raise ValueError("Run workflow and evidence condition are immutable")
        if saved_result.get("max_repairs", max_repairs) != max_repairs:
            raise ValueError("Run repair budget is immutable")
        if saved_result.get("status") not in {"provider_paused", "provider_failed"}:
            raise ValueError("Run is terminal; start a new trial rather than rewriting it")
        failure = saved_result.get("failure", {})
        if (
            retry_failed_call
            and failure.get("retryable") is False
            and not can_resume_prompt_rebuild(directory, failure)
        ):
            raise ValueError(
                "This failure cannot be retried; narrow the workflow or evidence scope"
            )
    else:
        provider = provider or "auto"
    if provider not in {"auto", "groq", "gemini", "openrouter"}:
        raise ValueError("unsupported provider")
    profile = model_profiles.for_provider(provider)
    context = (
        build_context(workspace, workflow, condition, profile=profile)
        if profile
        else build_context(workspace, workflow, condition)
    )
    if staged_read:
        if workflow != "read" or condition != "hybrid" or provider not in {"groq", "gemini"}:
            raise ValueError(
                "staged read requires read/hybrid with a fixed Groq or Gemini provider"
            )
        if seed_run_id is not None:
            raise ValueError("staged read starts with separate handler generation")
        saved_context = directory / "context.json"
        strategy = (
            json.loads(saved_context.read_text(encoding="utf-8")).get("read_generation_strategy")
            if saved_context.exists()
            else "staged-bodies-v3"
        )
        if strategy not in {"staged-bodies-v1", "staged-bodies-v2", "staged-bodies-v3"}:
            raise ValueError("saved run does not use a supported staged read strategy")
        context["read_generation_strategy"] = strategy
        response_contract = (
            json.loads(saved_context.read_text(encoding="utf-8")).get("read_response_contract")
            if saved_context.exists()
            else "explicit-response-contract-v1"
        )
        if response_contract:
            context["read_response_contract"] = response_contract
        format_recovery = (
            json.loads(saved_context.read_text(encoding="utf-8")).get("read_format_recovery")
            if saved_context.exists()
            else FORMAT_RECOVERY_POLICY
        )
        if format_recovery:
            context["read_format_recovery"] = format_recovery
        context["groq_reasoning_effort"] = (
            json.loads(saved_context.read_text(encoding="utf-8")).get(
                "groq_reasoning_effort", context["groq_reasoning_effort"]
            )
            if saved_context.exists()
            else groq_reasoning_effort or "medium"
        )
        if (
            groq_reasoning_effort is not None
            and groq_reasoning_effort != context["groq_reasoning_effort"]
        ):
            raise ValueError("saved reasoning effort is immutable; start a new trial")
        if strategy == "staged-bodies-v3":
            context = bind_read_stage_evidence(workspace, context)
    scaffold = candidate_scaffold(context)
    if (directory / "context.json").exists():
        saved = json.loads((directory / "context.json").read_text(encoding="utf-8"))
        if canonical_hash(saved) != canonical_hash(context):
            raise ValueError("Context changed; start a new trial rather than rewriting provenance")
    if saved_result and saved_result.get("context_sha256") != canonical_hash(context):
        raise ValueError("Run context checksum changed; start a new trial")
    write_json(directory / "context.json", context)
    seed_metadata_path = directory / "seed.json"
    if seed_metadata_path.exists():
        saved_seed = json.loads(seed_metadata_path.read_text(encoding="utf-8"))
        if seed_run_id is not None and seed_run_id != saved_seed.get("source_run_id"):
            raise ValueError("seed run identifier is immutable")
        seed_run_id = saved_seed.get("source_run_id")
    elif saved_result is not None and seed_run_id is not None:
        raise ValueError("this run was not created from a seed candidate")
    CallLedger(workspace).validate_existing(
        run_id,
        {
            "workflow": workflow,
            "condition": condition,
            "provider_policy": provider,
            "max_repairs": max_repairs,
            "context_sha256": canonical_hash(context),
        },
        seeded=seed_run_id is not None,
    )
    if seed_run_id is not None:
        _prepare_seed_candidate(workspace, directory, context, seed_run_id)
    if saved_result and not retry_failed_call:
        return saved_result

    if not retry_failed_call:
        for call_path in sorted(directory.glob("call-*.json")):
            try:
                call_attempt = int(call_path.stem.removeprefix("call-"))
            except ValueError:
                continue
            if (directory / f"draft-{call_attempt}.py").exists():
                continue
            failure_path = directory / f"provider-{call_attempt}.failure.json"
            if failure_path.is_file():
                failure_record = json.loads(failure_path.read_text(encoding="utf-8"))
                if failure_record.get("run_result"):
                    write_json(saved_result_path, failure_record["run_result"])
                    return failure_record["run_result"]
            failure = {
                "category": "interrupted_outcome_unrecorded",
                "message": (
                    "Prior provider request has no recorded response; retry requires "
                    "explicit opt-in."
                ),
                "attempt": call_attempt,
                "provider_policy": provider,
            }
            result = {
                "run_id": run_id,
                "workflow": workflow,
                "condition": condition,
                "provider_policy": provider,
                "max_repairs": max_repairs,
                "attempts": [],
                "status": "provider_paused",
                "failure": failure,
                "held_out_evaluated": False,
                "human_approved": False,
                "security_certified": False,
                "context_sha256": canonical_hash(context),
                "candidate_path": str(directory / f"draft-{call_attempt - 1}.py")
                if call_attempt > 0
                else None,
            }
            write_json(
                failure_path,
                {
                    **failure,
                    "run_result": result,
                },
            )
            write_json(saved_result_path, result)
            return result
    history, previous, feedback = [], None, None
    ledger, ledger_root = None, None
    for attempt in range(max_repairs + 1):
        path = directory / f"draft-{attempt}.py"
        fragment_path = directory / f"fragment-{attempt}.py"
        checkpoint(
            f"Reusing saved draft {attempt + 1}"
            if path.exists()
            else f"Generating draft {attempt + 1} using {provider}",
            attempt / 3,
        )
        if path.exists():
            source = path.read_text(encoding="utf-8")
            record = json.loads((directory / f"draft-{attempt}.json").read_text(encoding="utf-8"))
            if canonical_hash(source) != record["source_sha256"]:
                raise ValueError("Saved draft checksum differs")
            if scaffold:
                fragment = model_fragment(source, scaffold)
                if (
                    record.get("source_assembly") != source_assembly_metadata(scaffold, fragment)
                    or fragment_path.read_text(encoding="utf-8") != fragment
                ):
                    raise ValueError("Saved candidate fragment or assembly metadata differs")
            review = record["review"]
            # A crash/resume or repair seed must not bypass the current static policy.
            current_review = review_source(source)
            if review.get("status") == "blocked":
                current_review = {
                    **current_review,
                    "status": "blocked",
                    "findings": [*review.get("findings", []), *current_review.get("findings", [])],
                }
            review = current_review
        else:
            ledger = CallLedger(workspace)
            ledger_root = ledger.register(
                run_id,
                {
                    "workflow": workflow,
                    "condition": condition,
                    "provider_policy": provider,
                    "max_repairs": max_repairs,
                    "context_sha256": canonical_hash(context),
                },
            )
            remaining_budget = ledger.summary(ledger_root)
            try:
                if remaining_budget["remaining"] == 0:
                    raise CallBudgetExceeded("Trial lineage has exhausted its three-request budget")
                prepared = prepare_prompt(context, previous=previous, feedback=feedback)
                prompt = prepared["prompt"]
                response_format = prepared["response_format"]
            except (PromptBudgetExceeded, CallBudgetExceeded) as error:
                failure = {
                    "category": "call_budget_exhausted"
                    if isinstance(error, CallBudgetExceeded)
                    else "prompt_too_large",
                    "message": str(error),
                    "attempt": attempt,
                    "provider_policy": provider,
                    "retryable": False,
                    "local_rebuild_available": remaining_budget["remaining"] > 0
                    and attempt > 0
                    and (directory / f"draft-{attempt - 1}.py").is_file(),
                }
                result = {
                    "run_id": run_id,
                    "workflow": workflow,
                    "condition": condition,
                    "provider_policy": provider,
                    "max_repairs": max_repairs,
                    "attempts": history,
                    "status": "provider_failed",
                    "failure": failure,
                    "call_ledger": remaining_budget,
                    "held_out_evaluated": False,
                    "human_approved": False,
                    "security_certified": False,
                    "context_sha256": canonical_hash(context),
                    "candidate_path": str(directory / f"draft-{attempt - 1}.py")
                    if attempt > 0
                    else None,
                }
                audit_path = directory / f"provider-{attempt}.attempts.jsonl"
                with audit_path.open("a", encoding="utf-8") as audit:
                    audit.write(
                        json.dumps(
                            {"event": "request_rejected_locally", "category": failure["category"]}
                        )
                        + "\n"
                    )
                write_json(
                    directory / f"provider-{attempt}.failure.json",
                    {**failure, "run_result": result},
                )
                write_json(saved_result_path, result)
                return result
            call_path = directory / f"call-{attempt}.json"
            if call_path.exists() and not retry_failed_call:
                failure_path = directory / f"provider-{attempt}.failure.json"
                if failure_path.exists():
                    failure = json.loads(failure_path.read_text(encoding="utf-8"))
                    result = failure["run_result"]
                    write_json(saved_result_path, result)
                    return result
                # Earlier interrupted calls cannot be assumed unsent or free to repeat.
                failure = {
                    "category": "interrupted_outcome_unrecorded",
                    "message": (
                        "Prior provider request has no recorded response; retry requires "
                        "explicit opt-in."
                    ),
                    "attempt": attempt,
                    "provider_policy": provider,
                    "retryable": True,
                }
                result = {
                    "run_id": run_id,
                    "workflow": workflow,
                    "condition": condition,
                    "provider_policy": provider,
                    "max_repairs": max_repairs,
                    "attempts": history,
                    "status": "provider_paused",
                    "failure": failure,
                    "held_out_evaluated": False,
                    "human_approved": False,
                    "security_certified": False,
                    "context_sha256": canonical_hash(context),
                    "candidate_path": str(directory / f"draft-{attempt - 1}.py")
                    if attempt > 0
                    else None,
                }
                write_json(
                    directory / f"provider-{attempt}.failure.json",
                    {
                        "category": failure["category"],
                        "message": failure["message"],
                        "attempt": attempt,
                        "provider_policy": provider,
                        "run_result": result,
                    },
                )
                write_json(saved_result_path, result)
                return result
            pacing = workspace / "provider-last-call.json"
            source_view = prepared["source_view"]
            if source_view is not None:
                write_json(directory / f"source-view-{attempt}.json", source_view)
            last = json.loads(pacing.read_text()) if pacing.exists() else {"at": 0}
            interval = 4 if provider == "openrouter" else 65
            while (
                ledger.summary(ledger_root)["remaining"] > 0 and time.time() - last["at"] < interval
            ):
                checkpoint("Waiting for free-tier token window", attempt / 3)
                time.sleep(1)
            if ledger.summary(ledger_root)["remaining"] > 0 and not (
                attempt == 0
                and context.get("read_generation_strategy")
                in {"staged-bodies-v1", "staged-bodies-v2", "staged-bodies-v3"}
            ):
                write_json(pacing, {"at": time.time()})
            write_json(
                call_path,
                {
                    "prompt_sha256": canonical_hash(prompt),
                    "provider_policy": provider,
                    "requested_at": time.time(),
                    "response_format": response_format,
                    "generation_strategy": context.get("read_generation_strategy"),
                    "source_view_sha256": canonical_hash(source_view)
                    if source_view is not None
                    else None,
                    "repair_base_sha256": canonical_hash(previous)
                    if previous is not None
                    else None,
                    "held_out_in_context": False,
                    "ledger_version": 1,
                    "ledger_root_run_id": ledger_root,
                    "retry_number": (json.loads(call_path.read_text()).get("retry_number", 0) + 1)
                    if call_path.exists()
                    else 0,
                },
            )
            audit_path = directory / f"provider-{attempt}.attempts.jsonl"
            with audit_path.open("a", encoding="utf-8") as audit:
                audit.write(
                    json.dumps(
                        {
                            "event": "request_started",
                            "retry_number": json.loads(call_path.read_text(encoding="utf-8"))[
                                "retry_number"
                            ],
                            "requested_at": time.time(),
                            "prompt_sha256": canonical_hash(prompt),
                            "provider_policy": provider,
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
            reservations = []

            def before_request(name, model, *, request_prompt=None):
                try:
                    request_id = ledger.reserve(
                        run_id, attempt, name, model, canonical_hash(request_prompt or prompt)
                    )
                except (CallBudgetExceeded, ValueError) as error:
                    category = (
                        "call_budget_exhausted"
                        if isinstance(error, CallBudgetExceeded)
                        else "trial_protocol_violation"
                    )
                    raise ProviderFailure(
                        category,
                        [
                            {
                                "provider": name,
                                "category": category,
                            }
                        ],
                    ) from error
                reservations.append((request_id, name))
                with audit_path.open("a", encoding="utf-8") as audit:
                    audit.write(
                        json.dumps(
                            {
                                "event": "provider_request_reserved",
                                "request_id": request_id,
                                "provider": name,
                                "root_run_id": ledger_root,
                            },
                            sort_keys=True,
                        )
                        + "\n"
                    )

            try:
                if attempt == 0 and context.get("read_generation_strategy") in {
                    "staged-bodies-v1",
                    "staged-bodies-v2",
                    "staged-bodies-v3",
                }:
                    draft, provenance = _generate_read_stages(
                        context,
                        prompt,
                        directory,
                        workspace,
                        provider,
                        ledger,
                        reservations,
                        before_request,
                        checkpoint,
                    )
                else:
                    draft, provenance = generate(
                        prompt,
                        provider=provider,
                        repair=response_format == "edits",
                        before_request=before_request,
                        **(
                            {"groq_reasoning_effort": context["groq_reasoning_effort"]}
                            if context.get("groq_reasoning_effort")
                            else {}
                        ),
                        **(
                            {"response_format": response_format}
                            if response_format
                            in {
                                "source_lines",
                                "implementation_lines",
                                "read_handlers",
                                "read_bodies",
                                "read_with_update",
                                "line_edits",
                            }
                            else {}
                        ),
                    )
            except ProviderFailure as error:
                if reservations:
                    ledger.finish(reservations, error.attempts)
                failure = {
                    "category": error.category,
                    "attempts": error.attempts,
                    "prompt_sha256": canonical_hash(prompt),
                    "attempt": attempt,
                    "provider_policy": provider,
                }
                if error.category in {"call_budget_exhausted", "trial_protocol_violation"}:
                    failure["retryable"] = False
                prior_source = directory / f"draft-{attempt - 1}.py"
                result = {
                    "run_id": run_id,
                    "workflow": workflow,
                    "condition": condition,
                    "provider_policy": provider,
                    "max_repairs": max_repairs,
                    "attempts": history,
                    "status": "provider_paused"
                    if error.category == "quota_exhausted"
                    else "provider_failed",
                    "failure": failure,
                    "held_out_evaluated": False,
                    "human_approved": False,
                    "security_certified": False,
                    "context_sha256": canonical_hash(context),
                    "call_ledger": ledger.summary(ledger_root),
                    "candidate_path": str(prior_source) if prior_source.exists() else None,
                }
                write_json(
                    directory / f"provider-{attempt}.failure.json",
                    {**failure, "run_result": result},
                )
                with audit_path.open("a", encoding="utf-8") as audit:
                    audit.write(
                        json.dumps(
                            {
                                "event": "request_failed",
                                "category": error.category,
                                "attempts": error.attempts,
                            },
                            sort_keys=True,
                        )
                        + "\n"
                    )
                write_json(directory / "progress.json", history)
                write_json(saved_result_path, result)
                return result
            structured_response = provenance.pop("raw_structured_response", None)
            if structured_response is not None:
                response_path = directory / f"response-{attempt}.json"
                response_path.write_text(structured_response, encoding="utf-8", newline="\n")
                provenance["raw_structured_response_sha256"] = canonical_hash(structured_response)
            if reservations:
                ledger.finish(reservations, provenance.get("attempts", []))
                provenance["request_reservations"] = [item[0] for item in reservations]
            with audit_path.open("a", encoding="utf-8") as audit:
                audit.write(
                    json.dumps(
                        {
                            "event": "request_succeeded",
                            "provider": provenance["provider"],
                            "attempts": provenance.get("attempts", []),
                            "prompt_sha256": provenance["prompt_sha256"],
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
            repair_rejection = None
            repair_edits = None
            if context.get("read_format_recovery") == FORMAT_RECOVERY_POLICY:
                raw_proposal = draft.model_dump()
                prior_recoveries = len(provenance.get("format_recovery", []))
                if isinstance(draft, (GeneratedRangeRepair, GeneratedRepair)):
                    edits = (
                        draft.line_edits if isinstance(draft, GeneratedRangeRepair) else draft.edits
                    )
                    recovered = []
                    for index, edit in enumerate(edits):
                        raw = (
                            "\n".join(edit.new_lines)
                            if isinstance(draft, GeneratedRangeRepair)
                            else edit.new
                        )
                        normalized, recovery = recover_fstring_indices(raw)
                        if recovery is not None:
                            provenance.setdefault("format_recovery", []).append(
                                {"edit_index": index, **recovery}
                            )
                            updates = (
                                {"new_lines": normalized.split("\n")}
                                if isinstance(draft, GeneratedRangeRepair)
                                else {"new": normalized}
                            )
                            edit = edit.model_copy(update=updates)
                        recovered.append(edit)
                    draft = draft.model_copy(
                        update={
                            "line_edits"
                            if isinstance(draft, GeneratedRangeRepair)
                            else "edits": recovered
                        }
                    )
                else:
                    normalized, recovery = recover_fstring_indices(draft.source)
                    if recovery is not None:
                        provenance.setdefault("format_recovery", []).append(recovery)
                        draft = draft.model_copy(update={"source": normalized})
                if len(provenance.get("format_recovery", [])) > prior_recoveries:
                    raw_path = directory / f"parsed-proposal-{attempt}.json"
                    write_json(raw_path, raw_proposal)
                    provenance["pre_recovery_proposal"] = {
                        "file": raw_path.name,
                        "canonical_sha256": canonical_hash(raw_proposal),
                        "kind": "parsed_model_proposal",
                    }
            if isinstance(draft, GeneratedRangeRepair):
                repair_edits = [edit.model_dump() for edit in draft.line_edits]
                if previous is None or source_view is None:
                    raise ValueError("line repair has no previous candidate or source view")
                try:
                    source = apply_source_ranges(
                        previous, draft.line_edits, source_view=source_view
                    )
                except ValueError as error:
                    source = previous
                    repair_rejection = str(error)[:300]
            elif isinstance(draft, GeneratedRepair):
                repair_edits = [edit.model_dump() for edit in draft.edits]
                if previous is None:
                    raise ValueError("repair response has no previous candidate")
                try:
                    source = apply_source_edits(previous, draft.edits, source_view=source_view)
                except ValueError as error:
                    source = previous
                    repair_rejection = str(error)[:300]
            else:
                source = scaffold + draft.source
            assembly = {}
            if scaffold:
                fragment = model_fragment(source, scaffold)
                assembly = source_assembly_metadata(scaffold, fragment)
                fragment_path.write_text(fragment, encoding="utf-8")
            path.write_text(source, encoding="utf-8")
            review = review_source(source)
            if repair_rejection:
                review = {
                    **review,
                    "status": "blocked",
                    "certified_secure": False,
                    "findings": [
                        *review.get("findings", []),
                        {
                            "code": "invalid_repair_edit",
                            "rule": "invalid_repair_edit",
                            "severity": "error",
                            "message": repair_rejection,
                        },
                    ],
                }
            record = {
                "attempt": attempt,
                "provenance": provenance,
                "summary": draft.summary,
                "unknowns": draft.unknowns,
                "source_sha256": canonical_hash(source),
                "review": review,
                "evidence_ids": draft.evidence_ids,
                "response_format": response_format,
                **({"source_assembly": assembly} if assembly else {}),
            }
            if repair_edits is not None:
                record["repair_edits"] = repair_edits
            if repair_rejection:
                record["repair_rejection"] = repair_rejection
            write_json(directory / f"draft-{attempt}.json", record)
        interface_findings = []
        if scaffold:
            if fragment_is_evidence_echo(fragment):
                interface_findings = [{"rule": "fragment_echoed_evidence", "severity": "error"}]
            else:
                interface_findings = create_interface_findings(scaffold, fragment)
        if interface_findings:
            review = {
                **review,
                "status": "blocked",
                "certified_secure": False,
                "findings": [*review.get("findings", []), *interface_findings],
            }
        # Preserve the original draft review; record the actual execution gate separately.
        write_json(directory / f"execution-review-{attempt}.json", review)
        unsupported_evidence_ids = sorted(
            set(record.get("evidence_ids", [])) - supplied_evidence_ids(context)
        )
        if unsupported_evidence_ids:
            review = {
                **review,
                "status": "blocked",
                "certified_secure": False,
                "findings": [
                    *review.get("findings", []),
                    {
                        "code": "unsupported_evidence_id",
                        "rule": "unsupported_evidence_id",
                        "severity": "error",
                        "message": "Candidate cited evidence IDs absent from its request context.",
                        "evidence_ids": unsupported_evidence_ids,
                    },
                ],
            }
            record["review"] = review
            record["unsupported_evidence_ids"] = unsupported_evidence_ids
            write_json(directory / f"draft-{attempt}.json", record)
        if review["status"] == "blocked":
            unavailable = any(
                item.get("rule") == "target_static_review_unavailable"
                for item in review.get("findings", [])
            )
            evaluation = {
                "status": "runtime_failed" if unavailable else "static_review_blocked",
                "review": review,
            }
        else:
            checkpoint(f"Verifying draft {attempt + 1} in an independent container", attempt / 3)
            try:
                evaluation = evaluate_source(
                    source,
                    workspace,
                    workflow=None if workflow == "all" else workflow,
                    split="guidance",
                    checkpoint=checkpoint,
                )
            except CandidateRejected as error:
                diagnostic = str(error).rstrip()[-1800:]
                evaluation = {
                    "status": "candidate_boot_failed",
                    "detail": diagnostic.rsplit("\n", 1)[-1],
                    "diagnostics": diagnostic,
                }
            except RuntimeError as error:
                evaluation = {"status": "runtime_failed", "detail": str(error)[:1800]}
        write_json(directory / f"guidance-{attempt}.json", evaluation)
        history.append(
            {
                **record,
                "review": review,
                "evaluation_status": evaluation["status"],
                "passed_count": evaluation.get("passed_count", 0),
                "scenario_count": evaluation.get("scenario_count", 0),
            }
        )
        if evaluation["status"] in {"passed", "runtime_failed"}:
            previous = source
            write_json(directory / "progress.json", history)
            break
        if (
            ledger is not None
            and ledger_root is not None
            and ledger.summary(ledger_root)["remaining"] == 0
        ):
            # A staged draft may consume multiple reservations. Preserve its actual
            # verdict instead of entering a nonexistent next provider attempt.
            previous = source
            history[-1]["request_budget_exhausted"] = True
            write_json(directory / "progress.json", history)
            break
        next_feedback = _feedback_for_next_attempt(feedback, evaluation)
        invalid_syntax = any(
            item.get("rule") == "invalid_python"
            for item in review.get("findings", [])
            if isinstance(item, dict)
        )
        if (
            previous is not None
            and attempt < max_repairs
            and record.get("response_format") in {"edits", "line_edits"}
            and invalid_syntax
        ):
            rollback = {
                "reason": "repair_failed_syntax_review",
                "rejected_draft_sha256": canonical_hash(source),
                "next_repair_base_sha256": canonical_hash(previous),
                "raw_draft_preserved": True,
            }
            history[-1]["repair_rollback"] = rollback
            write_json(directory / f"repair-rollback-{attempt}.json", rollback)
            # Parser locations refer to the rejected proposal, not the next source view.
            restored_findings = [
                item
                for item in (feedback or {}).get("review", {}).get("findings", [])
                if isinstance(item, dict) and item.get("rule") == "invalid_python"
            ]
            next_feedback["review"] = {
                "status": "blocked",
                "findings": [
                    *restored_findings,
                    {
                        "rule": "invalid_repair_syntax",
                        "severity": "error",
                        "message": "Last proposed edit had invalid Python syntax. Its raw draft "
                        "was preserved, but the next numbered view is the pre-edit source. "
                        "Fix the guidance failures with complete, correctly indented edits.",
                    },
                ],
            }
            next_feedback["detail"] = (
                "The last patch failed syntax review. Repair the supplied pre-edit source; "
                "do not regenerate or repeat the invalid patch."
            )
        else:
            previous = source
        feedback = next_feedback
        write_json(directory / "progress.json", history)
    (directory / "app.py").write_text(previous, encoding="utf-8")
    result = {
        "run_id": run_id,
        "workflow": workflow,
        "condition": condition,
        "provider_policy": provider,
        "max_repairs": max_repairs,
        "attempts": history,
        "status": history[-1]["evaluation_status"],
        "held_out_evaluated": False,
        "human_approved": False,
        "security_certified": False,
        "context_sha256": canonical_hash(context),
        "candidate_path": str(directory / "app.py"),
    }
    if seed_run_id is not None:
        result["seeded_from_run_id"] = seed_run_id
    if ledger is not None and ledger_root is not None:
        result["call_ledger"] = ledger.summary(ledger_root)
        if result["status"] != "passed" and result["call_ledger"]["remaining"] == 0:
            result["stop_reason"] = "request_budget_exhausted"
    write_json(saved_result_path, result)
    return result


def finalize(workspace: Path, run_id: str, checkpoint=lambda *args: None) -> dict:
    if not run_id.isalnum():
        raise ValueError("invalid run identifier")
    directory = workspace / "runs" / run_id
    result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    if result["status"] != "passed":
        raise ValueError("candidate must pass guidance before final verification")
    destination = directory / "held-out.json"
    source = (directory / "app.py").read_text(encoding="utf-8")
    source_digest = canonical_hash(source)
    if source_digest != result["attempts"][-1]["source_sha256"]:
        raise ValueError("candidate changed after guidance; run a new trial")
    report = None
    if destination.exists():
        saved_report = json.loads(destination.read_text(encoding="utf-8"))
        if saved_report.get("source_sha256") != source_digest:
            raise ValueError("candidate changed after held-out verification; run a new trial")
        saved_digest = result.get("held_out_report_sha256")
        if saved_digest:
            if canonical_hash(saved_report) != saved_digest:
                raise ValueError("held-out report checksum differs; start a new trial")
            report = saved_report
    if report is None:
        report = evaluate_source(
            source,
            workspace,
            workflow=None if result["workflow"] == "all" else result["workflow"],
            split="held_out",
            checkpoint=checkpoint,
        )
        report["run_id"] = run_id
        report["repair_feedback_allowed"] = False
        write_json(destination, report)
    # Persist a summary, never the hidden observations, and make seeding guards durable.
    result["held_out_evaluated"] = True
    result["held_out_status"] = report["status"]
    result["held_out_passed_count"] = report["passed_count"]
    result["held_out_scenario_count"] = report["scenario_count"]
    result["held_out_report_sha256"] = canonical_hash(report)
    write_json(directory / "result.json", result)
    return report
