"""Local operator commands for the cross-language workbench."""

import argparse
import json
import os
from pathlib import Path

from legacylift.modernization.pipeline import finalize, migrate
from legacylift.modernization.study import prepare_study


def _worker_type(platform_name: str | None = None):
    """Select RQ's non-forking worker on Windows, where ``os.fork`` is unavailable."""
    from rq import SimpleWorker, Worker

    return SimpleWorker if (platform_name or os.name) == "nt" else Worker


def main(argv=None):
    parser = argparse.ArgumentParser(prog="legacylift v2")
    parser.add_argument("--home", type=Path, default=Path(".legacylift"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare", help="import, analyze and freeze the real legacy reference")
    commands.add_parser(
        "seal-study", help="validate existing frozen reference artifacts and seal guidance inputs"
    )
    proposal = commands.add_parser("migrate", help="generate and independently check a migration")
    proposal.add_argument("--workflow", choices=["read", "create", "update", "all"], default="all")
    proposal.add_argument(
        "--condition", choices=["source_only", "runtime_only", "hybrid"], default="hybrid"
    )
    proposal.add_argument(
        "--provider",
        choices=["auto", "groq", "gemini", "openrouter"],
        default=None,
        help="provider policy for a new run; resumes reuse the saved policy",
    )
    proposal.add_argument("--max-repairs", type=int, choices=[0, 1, 2], default=2)
    proposal.add_argument(
        "--staged-read",
        action="store_true",
        help="generate read/create bodies separately within the same request cap",
    )
    proposal.add_argument(
        "--groq-reasoning-effort",
        choices=["low", "medium", "high"],
        help="reasoning selection for a new staged read; saved runs retain their setting",
    )
    proposal.add_argument(
        "--run-id", help="resume an unchanged trial without discarding saved drafts"
    )
    proposal.add_argument(
        "--retry-failed-call",
        action="store_true",
        help="explicitly retry a provider request or resume a locally rejected repair prompt",
    )
    proposal.add_argument(
        "--seed-run-id",
        help=(
            "continue repair from an unevaluated, guidance-failing, or "
            "provider-paused candidate run"
        ),
    )
    verify = commands.add_parser(
        "finalize", help="final held-out verification without repair feedback"
    )
    verify.add_argument("run_id")
    serve = commands.add_parser("serve", help="serve the local workbench")
    serve.add_argument("--port", type=int, default=8010)
    serve.add_argument("--host", choices=["127.0.0.1", "localhost"], default="127.0.0.1")
    worker = commands.add_parser("worker", help="run the host-side RQ worker")
    worker.add_argument("--queue", default="legacylift")
    worker.add_argument("--redis-url", default=None)
    mutations = commands.add_parser(
        "verify-mutations", help="check that the frozen guidance comparator detects known faults"
    )
    mutations.add_argument("--output", type=Path, default=Path("artifacts/v2/mutation_report.json"))
    runtime_mutations = commands.add_parser(
        "verify-runtime-mutations",
        help="replay Redmine guidance and detect controlled runtime-observation faults",
    )
    runtime_mutations.add_argument(
        "--output", type=Path, default=Path("artifacts/v2/runtime_mutation_report.json")
    )
    candidate_mutations = commands.add_parser(
        "verify-candidate-mutations",
        help="run controlled candidate-source faults through the isolated Python runtime",
    )
    candidate_mutations.add_argument(
        "--output", type=Path, default=Path("artifacts/v2/candidate_mutation_report.json")
    )
    retrieval = commands.add_parser(
        "evaluate-retrieval", help="measure source retrieval using development relevance labels"
    )
    retrieval.add_argument(
        "--judgments", type=Path, default=Path("artifacts/v2/retrieval_judgments.json")
    )
    retrieval.add_argument(
        "--output", type=Path, default=Path("artifacts/v2/retrieval_report.json")
    )
    prompts = commands.add_parser(
        "audit-prompts", help="check all guidance-only request variants without provider calls"
    )
    prompts.add_argument(
        "--output", type=Path, default=Path("artifacts/v2/prompt_budget_report.json")
    )
    prompts.add_argument("--provider", choices=["groq", "gemini", "openrouter"], default="groq")
    study = commands.add_parser(
        "plan-study", help="freeze a prospective 27-trial design without API calls"
    )
    study.add_argument("--provider", choices=["groq", "gemini", "openrouter"], required=True)
    study.add_argument("--seed", type=int, default=20261117)
    study_audit = commands.add_parser(
        "audit-study", help="validate frozen study code/inputs and budgets"
    )
    study_audit.add_argument("study_id")
    study_run = commands.add_parser(
        "run-study", help="execute the next fixed-order study trials with no implicit retries"
    )
    study_run.add_argument("study_id")
    study_run.add_argument("--max-trials", type=int, choices=range(1, 28), default=1)
    study_report_parser = commands.add_parser(
        "study-report", help="audit recorded study outcomes without provider requests"
    )
    study_report_parser.add_argument("study_id")
    calls = commands.add_parser(
        "audit-calls", help="inspect a saved run's shared lineage request budget"
    )
    calls.add_argument("run_id")
    args = parser.parse_args(argv)
    from legacylift.cli import _load_project_env

    env_path = Path(".env")
    _load_project_env(env_path, include_provider_keys=False)
    needs_model_credentials = args.command in {"migrate", "worker", "run-study"} or (
        args.command == "serve" and not os.environ.get("LEGACYLIFT_REDIS_URL")
    )
    if needs_model_credentials:
        _load_project_env(env_path, include_provider_keys=True)

    def progress(message, value=0):
        print(json.dumps({"message": message, "progress": round(value, 3)}), flush=True)

    if args.command == "seal-study":
        from legacylift.modernization.frozen_study import seal_study

        seal = seal_study(args.home)
        print(
            json.dumps(
                {
                    "status": "sealed",
                    "seal_sha256": seal["seal_sha256"],
                    "parent_oracle_sha256": seal["parent_oracle_sha256"],
                    "provider_requests": 0,
                },
                indent=2,
            )
        )
        return 0

    if args.command in {"plan-study", "audit-study"}:
        from legacylift.modernization.controlled_study import audit_study_plan, create_study_plan

        if args.command == "plan-study":
            plan = create_study_plan(args.home, provider=args.provider, seed=args.seed)
            report = {
                "study_id": plan["study_id"],
                "trial_count": plan["trial_count"],
                "maximum_http_requests": plan["maximum_http_requests"],
                "state": "planned_only",
                "provider_requests": 0,
            }
        else:
            report = audit_study_plan(args.home, args.study_id)
        print(json.dumps(report, indent=2))
        return 0

    if args.command == "audit-calls":
        from legacylift.modernization.call_ledger import CallLedger

        if not args.run_id.isalnum():
            parser.error("invalid run identifier")
        ledger = CallLedger(args.home)
        result = ledger._read_json(ledger.runs / args.run_id / "result.json")
        binding = {
            key: result[key]
            for key in ("workflow", "condition", "provider_policy", "max_repairs", "context_sha256")
        }
        root = ledger.register(args.run_id, binding)
        print(json.dumps(ledger.summary(root), indent=2))
        return 0

    if args.command == "audit-prompts":
        from legacylift.modernization import model_profiles
        from legacylift.modernization.retrieval_evaluation import audit_prompt_budgets

        report = (
            audit_prompt_budgets(
                args.home, args.output, profile=model_profiles.for_provider(args.provider)
            )
            if model_profiles.for_provider(args.provider)
            else audit_prompt_budgets(args.home, args.output)
        )
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "variants": report["variant_count"],
                    "report": str(args.output),
                }
            )
        )
        return 0

    if args.command == "evaluate-retrieval":
        from legacylift.modernization.retrieval_evaluation import run_retrieval_evaluation

        report = run_retrieval_evaluation(args.home, args.judgments, args.output)
        print(json.dumps({"status": report["status"], "report": str(args.output)}))
        return 0

    if args.command == "worker":
        redis_url = args.redis_url or os.environ.get("LEGACYLIFT_REDIS_URL")
        if not redis_url:
            parser.error("worker needs LEGACYLIFT_REDIS_URL or --redis-url")
        from redis import Redis
        from rq import Queue

        connection = Redis.from_url(redis_url)
        try:
            connection.ping()
        except Exception as error:
            parser.error(f"cannot connect to the configured queue ({type(error).__name__})")
        _worker_type()([Queue(args.queue, connection=connection)], connection=connection).work()
        return 0

    if args.command in {
        "verify-mutations",
        "verify-runtime-mutations",
        "verify-candidate-mutations",
    }:
        from legacylift.modernization.mutations import (
            run_candidate_code_mutation_campaign,
            run_mutation_campaign,
            run_runtime_mutation_campaign,
        )

        if args.command == "verify-mutations":
            report = run_mutation_campaign(args.home, args.output)
        elif args.command == "verify-runtime-mutations":
            report = run_runtime_mutation_campaign(args.home, args.output, checkpoint=progress)
        else:
            report = run_candidate_code_mutation_campaign(
                args.home, args.output, checkpoint=progress
            )
        print(json.dumps(report, indent=2))
        return 0 if report["status"] == "passed" else 1

    if args.command == "serve":
        import uvicorn

        from .api import create_app

        uvicorn.run(create_app(args.home), host=args.host, port=args.port)
        return 0
    try:
        if args.command == "prepare":
            result = prepare_study(args.home, progress)
        elif args.command == "finalize":
            result = finalize(args.home, args.run_id, progress)
        elif args.command in {"run-study", "study-report"}:
            from legacylift.modernization.study_execution import run_study, study_report

            if args.command == "run-study":
                result = run_study(
                    args.home, args.study_id, max_trials=args.max_trials, checkpoint=progress
                )
            else:
                result = study_report(args.home, args.study_id)
            print(json.dumps(result, indent=2))
            return 0 if result.get("stop_reason") is None else 1
        else:
            result = migrate(
                args.home,
                workflow=args.workflow,
                condition=args.condition,
                provider=args.provider,
                max_repairs=args.max_repairs,
                run_id=args.run_id,
                retry_failed_call=args.retry_failed_call,
                seed_run_id=args.seed_run_id,
                staged_read=args.staged_read,
                groq_reasoning_effort=args.groq_reasoning_effort,
                checkpoint=progress,
            )
    except (RuntimeError, ValueError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in {"prepared", "already_prepared", "passed"} else 1
