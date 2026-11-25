"""Prospective, immutable 27-trial study planning; this module never calls a model."""

from __future__ import annotations

import json
import os
import random
import uuid
from pathlib import Path

from legacylift.runtimes.python_target import PYTHON_IMAGE
from legacylift.runtimes.redmine import REDMINE_IMAGE, REDMINE_SOURCE_COMMIT

from . import model_profiles, openrouter
from .call_ledger import CALL_LIMIT, CallLedger
from .contracts import canonical_hash, contract_manifest
from .frozen_study import evaluation_artifact
from .generation import (
    GEMINI_MODEL,
    build_context,
    configured_groq_model,
    groq_request_parameters,
    prompt_for,
)
from .protocol import code_hashes, input_hashes


def _root_manifest(plan: dict, cell: dict) -> dict:
    return {
        "version": 1,
        "scope": "controlled",
        "root_run_id": cell["run_id"],
        "study_id": plan["study_id"],
        "study_manifest_sha256": plan["manifest_sha256"],
        "call_limit": CALL_LIMIT,
        "provider": plan["provider"],
        "model": plan["model"],
        "code_sha256": plan["code_sha256"],
        "input_sha256": plan["input_sha256"],
    }


def _binding(plan: dict, cell: dict) -> dict:
    return {
        "workflow": cell["workflow"],
        "condition": cell["condition"],
        "provider_policy": plan["provider"],
        "max_repairs": 2,
        "context_sha256": cell["context_sha256"],
    }


def create_study_plan(workspace: Path, *, provider: str, seed: int = 20261117) -> dict:
    if provider not in {"groq", "gemini", "openrouter"}:
        raise ValueError("controlled study requires a fixed provider; auto fallback is disabled")
    model = (
        configured_groq_model()
        if provider == "groq"
        else openrouter.configured_model()
        if provider == "openrouter"
        else (os.getenv("LEGACYLIFT_GEMINI_MODEL") or GEMINI_MODEL)
    )
    guidance, _ = evaluation_artifact(workspace, "guidance")
    contexts = {}
    for workflow in ("read", "create", "update"):
        for condition in ("source_only", "runtime_only", "hybrid"):
            context = (
                build_context(
                    workspace, workflow, condition, profile=model_profiles.for_provider(provider)
                )
                if model_profiles.for_provider(provider)
                else build_context(workspace, workflow, condition)
            )
            prompt_for(context)
            contexts[(workflow, condition)] = canonical_hash(context)
    cells = [
        {
            "run_id": uuid.uuid4().hex,
            "workflow": workflow,
            "condition": condition,
            "replicate": replicate,
            "context_sha256": context_sha,
        }
        for (workflow, condition), context_sha in contexts.items()
        for replicate in (1, 2, 3)
    ]
    random.Random(seed).shuffle(cells)
    plan = {
        "version": "redmine-issues-controlled-1",
        "study_id": uuid.uuid4().hex,
        "provider": provider,
        "model": model,
        "shuffle_seed": seed,
        "trial_count": 27,
        "maximum_http_requests": 27 * CALL_LIMIT,
        "max_repairs_per_trial": 2,
        "temperature": groq_request_parameters(model).get("temperature", 0)
        if provider == "groq"
        else 0,
        "source_commit": REDMINE_SOURCE_COMMIT,
        "reference_image": REDMINE_IMAGE,
        "target_image": PYTHON_IMAGE,
        "contract_sha256": canonical_hash(contract_manifest()),
        "parent_oracle_sha256": guidance["oracle_sha256"],
        "code_sha256": code_hashes(),
        "input_sha256": input_hashes(workspace),
        "cells": cells,
        "execution_state": "planned_only",
        "provider_requests_at_creation": 0,
        "held_out_observations_read": False,
        "limits": [
            "Exploratory runs are excluded from this prospective design.",
            "Existing model and shared-contract knowledge remain possible confounders.",
            "Provider outputs are not deterministic even with temperature zero.",
            "No migration or controlled-study acceptance gate is established by this plan.",
        ],
    }
    plan["manifest_sha256"] = canonical_hash(plan)
    directory = workspace / "experiments" / plan["study_id"]
    directory.mkdir(parents=True, exist_ok=False)
    with (directory / "manifest.json").open("x", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    ledger = CallLedger(workspace)
    for cell in cells:
        ledger.register(cell["run_id"], _binding(plan, cell), manifest=_root_manifest(plan, cell))
    return plan


def audit_study_plan(workspace: Path, study_id: str) -> dict:
    if len(study_id) != 32 or any(char not in "0123456789abcdef" for char in study_id):
        raise ValueError("invalid study identifier")
    path = workspace / "experiments" / study_id / "manifest.json"
    if path.is_symlink() or not path.resolve().is_relative_to(workspace.resolve()):
        raise ValueError("study manifest escaped its workspace")
    plan = json.loads(path.read_text(encoding="utf-8"))
    digest = plan.pop("manifest_sha256")
    if plan.get("study_id") != study_id or canonical_hash(plan) != digest:
        raise ValueError("study manifest checksum differs")
    plan["manifest_sha256"] = digest
    if plan["code_sha256"] != code_hashes() or plan["input_sha256"] != input_hashes(workspace):
        raise ValueError("controlled study code or inputs changed; start a new versioned plan")
    if len(plan["cells"]) != 27 or len({cell["run_id"] for cell in plan["cells"]}) != 27:
        raise ValueError("controlled study cells are missing or duplicated")
    expected = {
        (workflow, condition, replicate)
        for workflow in ("read", "create", "update")
        for condition in ("source_only", "runtime_only", "hybrid")
        for replicate in (1, 2, 3)
    }
    if {
        (cell["workflow"], cell["condition"], cell["replicate"]) for cell in plan["cells"]
    } != expected:
        raise ValueError("controlled study must retain all 27 distinct design cells")
    for cell in plan["cells"]:
        context = (
            build_context(
                workspace,
                cell["workflow"],
                cell["condition"],
                profile=model_profiles.for_provider(plan["provider"]),
            )
            if model_profiles.for_provider(plan["provider"])
            else build_context(workspace, cell["workflow"], cell["condition"])
        )
        if canonical_hash(context) != cell["context_sha256"]:
            raise ValueError("controlled study context changed")
    ledger = CallLedger(workspace)
    trials = []
    for cell in plan["cells"]:
        usage = ledger.summary(cell["run_id"])
        if usage["manifest_sha256"] != canonical_hash(_root_manifest(plan, cell)):
            raise ValueError("controlled trial ledger manifest differs")
        trials.append(
            {
                **cell,
                "requests_consumed": usage["legacy_requests_consumed"] + usage["reserved_requests"],
                "budget_remaining": usage["remaining"],
            }
        )
    return {
        "study_id": study_id,
        "protocol_valid": True,
        "trial_count": 27,
        "maximum_http_requests": 81,
        "requests_consumed": sum(c["requests_consumed"] for c in trials),
        "state": "planned_or_in_progress",
        "trials": trials,
    }
