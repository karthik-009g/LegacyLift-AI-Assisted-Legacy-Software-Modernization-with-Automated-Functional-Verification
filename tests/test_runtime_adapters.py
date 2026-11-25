from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from legacylift.runtimes.models import RuntimeRequest, RuntimeResponse
from legacylift.runtimes.redmine import (
    REDMINE_IMAGE,
    RedmineReference,
    RuntimeUnavailable,
    parse_issue_routes,
)
from legacylift.runtimes.reference_gate import verify_reference


@pytest.mark.parametrize(
    "path", ["https://example.com", "//example.com/path", "relative", "/x\nGET /y"]
)
def test_runtime_requests_cannot_change_host_or_inject_control_characters(path):
    with pytest.raises(ValidationError, match="local absolute path"):
        RuntimeRequest(method="GET", path=path)


def test_runtime_response_preserves_types_and_empty_body():
    response = RuntimeResponse.model_validate_json(
        '{"status":204,"headers":{},"json":null,"body_bytes":0}'
    )
    assert response.json_body is None
    assert response.status == 204
    with pytest.raises(ValidationError):
        RuntimeRequest(method="GET", path="/", fixture_epoch=1)


def test_redmine_preflight_retries_only_transient_missing_image(monkeypatch):
    runtime = RedmineReference()
    attempts = 0

    def inspect(arguments, *, payload=None):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeUnavailable("Docker image failed: No such image: pinned-redmine")
        return "sha256:pinned-image-id"

    monkeypatch.setattr(runtime, "_run", inspect)
    monkeypatch.setattr("legacylift.runtimes.redmine.time.sleep", lambda _delay: None)

    assert runtime._verify_pinned_image() == "sha256:pinned-image-id"
    assert attempts == 2


def test_redmine_preflight_does_not_retry_other_docker_errors(monkeypatch):
    runtime = RedmineReference()
    attempts = 0

    def inspect(arguments, *, payload=None):
        nonlocal attempts
        attempts += 1
        raise RuntimeUnavailable("Docker daemon unavailable")

    monkeypatch.setattr(runtime, "_run", inspect)
    with pytest.raises(RuntimeUnavailable, match="daemon unavailable"):
        runtime._verify_pinned_image()
    assert attempts == 1


def test_redmine_preflight_verifies_digest_through_local_tag_when_qualified_lookup_fails(
    monkeypatch,
):
    runtime = RedmineReference()
    commands = []
    image_id = "sha256:d26185b803ec88617d101a041c3614c136385011fd0d7b2c6acb8cacb58e6e1e"

    def inspect(arguments, *, payload=None):
        commands.append(arguments)
        if len(arguments) > 2 and "@sha256:" in arguments[2]:
            raise RuntimeUnavailable(f"Docker image failed: No such image: {arguments[2]}")
        if "{{json .RepoDigests}}|{{.Id}}" in arguments:
            return f'["redmine@{REDMINE_IMAGE.rsplit("@", 1)[1]}"]|{image_id}'
        raise AssertionError("unexpected Docker image inspection")

    monkeypatch.setattr(runtime, "_run", inspect)
    monkeypatch.setattr("legacylift.runtimes.redmine.time.sleep", lambda _delay: None)

    assert runtime._verify_pinned_image() == image_id
    assert len(commands) == 3
    assert commands[-1][2] == "redmine:4.2.10"


def test_redmine_preflight_rejects_local_tag_with_a_different_digest(monkeypatch):
    runtime = RedmineReference()

    def inspect(arguments, *, payload=None):
        if len(arguments) > 2 and "@sha256:" in arguments[2]:
            raise RuntimeUnavailable("Docker image failed: No such image")
        return '["redmine@sha256:' + "0" * 64 + '"]|sha256:' + "1" * 64

    monkeypatch.setattr(runtime, "_run", inspect)
    monkeypatch.setattr("legacylift.runtimes.redmine.time.sleep", lambda _delay: None)

    with pytest.raises(RuntimeUnavailable, match="does not match the pinned digest"):
        runtime._verify_pinned_image()


def test_issue_route_parser_keeps_actual_controller_routes_and_each_verb():
    route_table = "\n".join(
        [
            "                         issue GET /issues/:id(.:format) issues#show",
            "                                       POST /issues(.:format) issues#create",
            "                                       PUT|PATCH /issues/:id(.:format) issues#update",
            "                         comment GET /issues/:id/comments comments#show",
            "project_issue GET /projects/:project_id/issues(.:format) issues#index",
        ]
    )

    routes = parse_issue_routes(route_table)

    assert {(item["method"], item["path"], item["action"]) for item in routes} == {
        ("GET", "/issues/:id(.:format)", "show"),
        ("POST", "/issues(.:format)", "create"),
        ("PUT", "/issues/:id(.:format)", "update"),
        ("PATCH", "/issues/:id(.:format)", "update"),
    }
    assert len({item["evidence_id"] for item in routes}) == len(routes)


def test_reference_launch_keeps_application_unprivileged_and_without_host_secrets(monkeypatch):
    commands = []
    runtime = RedmineReference()
    monkeypatch.setattr(
        "legacylift.runtimes.redmine.reference_image", lambda *args, **_kwargs: REDMINE_IMAGE
    )

    def fake_run(arguments, *, payload=None):
        commands.append(arguments)
        if arguments[0] == "run":
            return "owned-container-id\n"
        if "runner" in arguments:
            return '{"issue_id":1}\n'
        if "/legacylift/request_proxy.rb" in arguments:
            return '{"status":200,"headers":{},"json":{},"body_bytes":2}'
        return ""

    monkeypatch.setattr(runtime, "_run", fake_run)
    runtime.start()
    launch = next(command for command in commands if command[0] == "run")
    assert REDMINE_IMAGE in launch
    assert "--network=none" in launch
    assert "--read-only" in launch
    assert "--user=999:999" in launch
    assert "--cap-drop=ALL" in launch
    assert "--pids-limit=128" in launch
    assert not any("GROQ_API_KEY" in value or "GEMINI_API_KEY" in value for value in launch)
    assert all("readonly" in value for value in launch if value.startswith("type=bind"))
    runtime.stop()
    assert commands[-1] == ["rm", "--force", "owned-container-id"]


def test_reference_cleanup_is_attempted_when_initialization_fails(monkeypatch):
    runtime = RedmineReference()
    monkeypatch.setattr(
        "legacylift.runtimes.redmine.reference_image", lambda *args, **_kwargs: REDMINE_IMAGE
    )
    commands = []

    def fake_run(arguments, *, payload=None):
        commands.append(arguments)
        if arguments[0] == "run":
            return "owned-container-id"
        if "db:migrate" in arguments:
            raise RuntimeUnavailable("synthetic initialization failure")
        return ""

    monkeypatch.setattr(runtime, "_run", fake_run)
    with pytest.raises(RuntimeUnavailable, match="initialization failure"):
        runtime.start()
    assert commands[-1] == ["rm", "--force", "owned-container-id"]


class _FakeReference:
    def __init__(self, *, mismatch=False):
        self.fixture = {
            "issue_id": 1,
            "project_id": 1,
            "tracker_id": 1,
            "status_ids": {"closed": 5, "in_progress": 2},
        }
        self.mismatch = mismatch

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def describe(self):
        return {"network": "none", "read_only_root": True, "user": "999:999", "published_ports": {}}

    def snapshot(self):
        return {"issues": [], "journals": [{"id": 1}], "journal_details": []}

    def request(self, request):
        status = 200
        if request.actor != "alice":
            status = 403
        elif request.method == "POST":
            status = 201
        elif request.method == "PUT":
            status = 204
        return RuntimeResponse(
            status=status, headers={}, json={"changed": self.mismatch}, body_bytes=2
        )


def test_reference_gate_detects_non_reproducible_replays(tmp_path):
    references = iter([_FakeReference(), _FakeReference(mismatch=True)])
    result = verify_reference(tmp_path, reference_factory=lambda: next(references))
    assert result["status"] == "failed"
    assert result["checks"]["independent_replays_match"] is False
    assert result["migration_performed"] is False
    stored = json.loads((tmp_path / "reference_gate.json").read_text())
    assert stored == result
