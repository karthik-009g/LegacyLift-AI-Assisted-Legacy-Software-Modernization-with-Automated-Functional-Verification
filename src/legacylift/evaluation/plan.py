"""Explicit scenario partition for the initial LegacyLift evaluation."""

from __future__ import annotations

from legacylift.runtime_capture.models import Scenario

GUIDANCE_SCENARIO_IDS = (
    "create_ticket",
    "retrieve_owned_ticket",
    "valid_status_transitions",
)
HELD_OUT_SCENARIO_IDS = (
    "hide_other_users_ticket",
    "reject_empty_subject",
    "reject_skipped_status",
)


def split_scenarios(
    scenarios: tuple[Scenario, ...],
) -> tuple[tuple[Scenario, ...], tuple[Scenario, ...]]:
    """Split known scenarios and reject unclassified or duplicate inputs."""
    scenario_ids = [scenario.scenario_id for scenario in scenarios]
    if len(scenario_ids) != len(set(scenario_ids)):
        raise ValueError("scenario IDs must be unique")

    expected_ids = set(GUIDANCE_SCENARIO_IDS) | set(HELD_OUT_SCENARIO_IDS)
    actual_ids = set(scenario_ids)
    if actual_ids != expected_ids:
        missing = sorted(expected_ids - actual_ids)
        unclassified = sorted(actual_ids - expected_ids)
        raise ValueError(
            f"evaluation scenario partition is incomplete: missing={missing}, "
            f"unclassified={unclassified}"
        )

    by_id = {scenario.scenario_id: scenario for scenario in scenarios}
    guidance = tuple(by_id[scenario_id] for scenario_id in GUIDANCE_SCENARIO_IDS)
    held_out = tuple(by_id[scenario_id] for scenario_id in HELD_OUT_SCENARIO_IDS)
    return guidance, held_out
