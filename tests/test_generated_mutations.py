"""Mutation measurements require a working control and semantic, not infrastructure, failures."""

import json

import pytest

from legacylift.modernization import generated_mutations as campaign
from legacylift.modernization.contracts import canonical_hash


@pytest.mark.parametrize("outcome", ["bad_baseline", "transport_failure", "survivor", "detected"])
def test_campaign_does_not_confuse_untested_or_infrastructure_failure_with_a_kill(
    tmp_path, monkeypatch, outcome
):
    directory = tmp_path / "runs/control"
    directory.mkdir(parents=True)
    source = "value = 1\n"
    (directory / "app.py").write_text(source)
    (directory / "result.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "workflow": "update",
                "attempts": [
                    {
                        "source_sha256": canonical_hash(source),
                        "provenance": {"provider": "groq"},
                    }
                ],
            }
        )
    )
    variant = {
        "mutation_id": "control",
        "scenario_id": "update.advance",
        "expected_mismatch_path": "steps[0].response.status",
        "source": "value = 2\n",
        "source_sha256": canonical_hash("value = 2\n"),
    }
    monkeypatch.setattr(campaign, "update_source_mutations", lambda code: [variant])
    calls = []

    def evaluate(code, home, *, workflow, split):
        assert workflow == "update" and split == "guidance"
        calls.append(code)
        if code == source:
            return {
                "source_sha256": canonical_hash(code),
                "scenario_count": 6,
                "passed_count": 5 if outcome == "bad_baseline" else 6,
                "status": "compatibility_failed" if outcome == "bad_baseline" else "passed",
            }
        if outcome == "transport_failure":
            raise RuntimeError("Synthetic Docker transport failure")
        detected = outcome == "detected"
        return {
            "status": "compatibility_failed" if detected else "passed",
            "passed_count": 5 if detected else 6,
            "scenario_count": 6,
            "results": [
                {
                    "scenario_id": "update.advance",
                    "passed": not detected,
                    "mismatches": [{"path": "steps[0].response.status"}] if detected else [],
                }
            ],
        }

    output = tmp_path / "measurement.json"
    report = campaign.run_generated_mutations(tmp_path, "control", output, evaluator=evaluate)
    assert (
        report["status"]
        == {
            "bad_baseline": "baseline_mismatch",
            "transport_failure": "measurement_failed",
            "survivor": "failed",
            "detected": "passed",
        }[outcome]
    )
    assert report["detected_count"] == (1 if outcome == "detected" else 0)
    assert len(calls) == (1 if outcome == "bad_baseline" else 2)
    assert (directory / "app.py").read_text() == source
    with pytest.raises(ValueError, match="preserve the previous"):
        campaign.run_generated_mutations(tmp_path, "control", output, evaluator=evaluate)


def test_curated_mutation_plan_rejects_an_unrecognized_source():
    with pytest.raises(ValueError, match="mutation anchor"):
        campaign.update_source_mutations("print('not the measured implementation')\n")
