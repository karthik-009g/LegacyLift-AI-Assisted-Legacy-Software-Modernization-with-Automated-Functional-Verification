"""Fixed, synthetic scenarios used to observe legacy ticket behavior."""

from .models import Scenario, ScenarioStep

DEFAULT_SCENARIOS = (
    Scenario(
        scenario_id="create_ticket",
        description="An owner creates a ticket with normalized text.",
        steps=(
            ScenarioStep("start_session", "POST", "/session", {"user_id": "alice"}),
            ScenarioStep(
                "create_ticket",
                "POST",
                "/tickets",
                {"subject": "  Capture scenario  ", "description": "  Synthetic request.  "},
            ),
        ),
    ),
    Scenario(
        scenario_id="retrieve_owned_ticket",
        description="An owner retrieves the seeded synthetic ticket.",
        steps=(
            ScenarioStep("start_session", "POST", "/session", {"user_id": "alice"}),
            ScenarioStep("get_owned_ticket", "GET", "/tickets/1"),
        ),
    ),
    Scenario(
        scenario_id="hide_other_users_ticket",
        description="A different session owner receives not found for the seeded ticket.",
        steps=(
            ScenarioStep("start_session", "POST", "/session", {"user_id": "bob"}),
            ScenarioStep("get_unowned_ticket", "GET", "/tickets/1"),
        ),
    ),
    Scenario(
        scenario_id="reject_empty_subject",
        description="Ticket creation rejects an empty subject without changing the database.",
        steps=(
            ScenarioStep("start_session", "POST", "/session", {"user_id": "alice"}),
            ScenarioStep("create_invalid_ticket", "POST", "/tickets", {"subject": "  "}),
        ),
    ),
    Scenario(
        scenario_id="valid_status_transitions",
        description="The owner advances a ticket through both allowed status transitions.",
        steps=(
            ScenarioStep("start_session", "POST", "/session", {"user_id": "alice"}),
            ScenarioStep(
                "move_to_in_progress",
                "PATCH",
                "/tickets/1/status",
                {"status": "in_progress"},
            ),
            ScenarioStep(
                "close_ticket",
                "PATCH",
                "/tickets/1/status",
                {"status": "closed"},
            ),
        ),
    ),
    Scenario(
        scenario_id="reject_skipped_status",
        description="The application rejects skipping directly from open to closed.",
        steps=(
            ScenarioStep("start_session", "POST", "/session", {"user_id": "alice"}),
            ScenarioStep(
                "skip_to_closed",
                "PATCH",
                "/tickets/1/status",
                {"status": "closed"},
            ),
        ),
    ),
)
