"""Pinned, disposable Redmine reference; no application code runs on the host."""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from .images import reference_image
from .models import RuntimeRequest, RuntimeResponse

REDMINE_IMAGE = (
    "redmine:4.2.10@sha256:d26185b803ec88617d101a041c3614c136385011fd0d7b2c6acb8cacb58e6e1e"
)
REDMINE_SOURCE_COMMIT = "9118c6dcb4ffe203f7029eb89523cd8a56b85cde"
FIXTURE_EPOCH = 1768478400
ASSETS = Path(__file__).parent / "assets"


class RuntimeUnavailable(RuntimeError):
    """The Docker infrastructure or approved profile could not be prepared."""


def parse_issue_routes(route_table: str) -> list[dict[str, str | None]]:
    """Extract selected issue-controller rows from Rails' generated route table."""
    supported_actions = {"show", "create", "update"}
    routes = []
    for line in route_table.splitlines():
        columns = line.split()
        target_index = next(
            (
                index
                for index, value in enumerate(columns)
                if value.startswith("issues#") and value.partition("#")[2] in supported_actions
            ),
            None,
        )
        if target_index is None or target_index < 2:
            continue
        path, verb_column = columns[target_index - 1], columns[target_index - 2]
        methods = verb_column.split("|")
        if not path.startswith("/") or any(not method.isalpha() for method in methods):
            continue
        route_name = columns[target_index - 3] if target_index >= 3 else None
        controller, action = columns[target_index].split("#", maxsplit=1)
        for method in methods:
            identity = "\0".join((route_name or "", method, path, controller, action))
            routes.append(
                {
                    "evidence_id": "route:" + hashlib.sha256(identity.encode()).hexdigest()[:16],
                    "route_name": route_name,
                    "method": method,
                    "path": path,
                    "controller": controller,
                    "action": action,
                }
            )
    return sorted(routes, key=lambda item: (item["path"] or "", item["method"] or ""))


class RedmineReference:
    """All storage is container-local tmpfs; stop removes only this owned container."""

    def __init__(self, *, docker: str = "docker", timeout: float = 120) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.docker = docker
        self.timeout = timeout
        self.name = f"legacylift-redmine-{uuid.uuid4().hex[:12]}"
        self.container_id: str | None = None
        self.fixture: dict[str, Any] = {}
        self.logs: list[dict[str, Any]] = []
        self.image: str | None = None

    def _run(self, arguments: list[str], *, payload: str | None = None) -> str:
        try:
            completed = subprocess.run(
                [self.docker, *arguments],
                input=payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as error:
            raise RuntimeUnavailable(f"Docker operation failed: {type(error).__name__}") from error
        self.logs.append({"operation": arguments[0], "exit_code": completed.returncode})
        if completed.returncode:
            detail = completed.stderr.strip()[-1500:] or completed.stdout.strip()[-1500:]
            raise RuntimeUnavailable(f"Docker {arguments[0]} failed: {detail}")
        return completed.stdout

    def _exec(self, *arguments: str, payload: str | None = None) -> str:
        if not self.container_id:
            raise RuntimeUnavailable("reference container is not running")
        return self._run(
            ["exec", *(["-i"] if payload is not None else []), self.container_id, *arguments],
            payload=payload,
        )

    def start(self) -> None:
        if self.container_id:
            raise RuntimeUnavailable("reference already started")
        self._run(["info", "--format", "{{.ServerVersion}}"])
        base_image_id = self._verify_pinned_image()
        try:
            self.image = reference_image(REDMINE_IMAGE, ASSETS, base_image_id=base_image_id)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            raise RuntimeUnavailable(
                f"reference image preparation failed: {str(error)[:500]}"
            ) from error
        arguments = [
            "run",
            "--detach",
            "--pull=never",
            "--name",
            self.name,
            "--label",
            "io.legacylift.role=reference",
            "--label",
            "io.legacylift.profile=redmine-4.2.10",
            "--network=none",
            "--read-only",
            "--user=999:999",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--memory=1g",
            "--cpus=2",
            "--pids-limit=128",
            "--env",
            "HOME=/tmp",
            "--env",
            "SCHEMA=/tmp/legacylift-schema.rb",
            "--env",
            "RUBYOPT=-r/legacylift/fixture_clock.rb",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=128m,mode=1777",
        ]
        for name, size in (("tmp", 32), ("log", 16), ("sqlite", 64), ("files", 16)):
            arguments += [
                "--tmpfs",
                f"/usr/src/redmine/{name}:rw,nosuid,nodev,size={size}m,uid=999,gid=999",
            ]
        arguments += ["--entrypoint", "sleep", self.image, "infinity"]
        self.container_id = self._run(arguments).strip()
        try:
            self._exec("bundle", "exec", "rake", "db:migrate")
            self._run(
                [
                    "exec",
                    "--env",
                    "REDMINE_LANG=en",
                    self.container_id,
                    "bundle",
                    "exec",
                    "rake",
                    "redmine:load_default_data",
                ]
            )
            seed_output = self._exec(
                "bundle", "exec", "rails", "runner", "/legacylift/redmine_seed.rb"
            )
            self.fixture = json.loads(seed_output.strip().splitlines()[-1])
            self._exec(
                "ruby",
                "-rfileutils",
                "-e",
                "FileUtils.cp('/usr/src/redmine/sqlite/reference.sqlite3', "
                "'/tmp/legacylift-baseline.sqlite3')",
            )
            self._run(
                [
                    "exec",
                    "--detach",
                    self.container_id,
                    "bundle",
                    "exec",
                    "rails",
                    "server",
                    "-b",
                    "127.0.0.1",
                    "-p",
                    "3000",
                    "-P",
                    "/tmp/legacylift-server.pid",
                ]
            )
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                try:
                    response = self.request(
                        RuntimeRequest(
                            method="GET",
                            path=f"/issues/{self.fixture['issue_id']}.json",
                            actor="alice",
                        )
                    )
                    if response.status == 200:
                        return
                except RuntimeUnavailable:
                    pass
                time.sleep(0.5)
            raise RuntimeUnavailable("legacy server did not become ready within 45 seconds")
        except Exception:
            self.stop()
            raise

    def _verify_pinned_image(self) -> str:
        """Verify the pinned digest and recover from digest-name lookup glitches."""
        arguments = ["image", "inspect", REDMINE_IMAGE, "--format", "{{.Id}}"]
        for attempt in range(2):
            try:
                return self._run(arguments).strip()
            except RuntimeUnavailable as error:
                if "no such image" not in str(error).lower():
                    raise
                if attempt == 0:
                    time.sleep(0.25)

        image_name, separator, expected_digest = REDMINE_IMAGE.partition("@")
        if not separator or not expected_digest.startswith("sha256:"):
            raise RuntimeUnavailable("pinned Redmine image reference is malformed")
        try:
            metadata = self._run(
                [
                    "image",
                    "inspect",
                    image_name,
                    "--format",
                    "{{json .RepoDigests}}|{{.Id}}",
                ]
            ).strip()
        except RuntimeUnavailable as error:
            raise RuntimeUnavailable("pinned Redmine image is unavailable locally") from error
        repo_digests_json, separator, image_id = metadata.partition("|")
        try:
            repo_digests = json.loads(repo_digests_json)
        except json.JSONDecodeError as error:
            raise RuntimeUnavailable("local Redmine image has invalid digest metadata") from error
        if (
            not separator
            or not isinstance(repo_digests, list)
            or expected_digest not in {value.rsplit("@", 1)[-1] for value in repo_digests}
            or not image_id.startswith("sha256:")
        ):
            raise RuntimeUnavailable("local Redmine image does not match the pinned digest")
        return image_id

    def request(self, request: RuntimeRequest) -> RuntimeResponse:
        payload = {
            "method": request.method,
            "path": request.path,
            "actor": request.actor,
            "json": request.json_body,
        }
        if request.fixture_epoch is not None:
            payload["fixture_epoch"] = request.fixture_epoch
        output = self._exec("ruby", "/legacylift/request_proxy.rb", payload=json.dumps(payload))
        return RuntimeResponse.model_validate_json(output.strip())

    def snapshot(self) -> dict[str, Any]:
        return json.loads(self._exec("ruby", "/legacylift/redmine_snapshot.rb"))

    def reset(self) -> None:
        self._exec("ruby", "/legacylift/reset_database.rb")

    def issue_routes(self) -> list[dict[str, str | None]]:
        """Read actual route dispatch facts from the isolated pinned Rails router."""
        output = self._exec("bundle", "exec", "rake", "routes")
        routes = parse_issue_routes(output)
        if not routes:
            raise RuntimeUnavailable("pinned Rails router returned no issue route facts")
        return routes

    def fixture_bytes(self) -> bytes:
        """Only synthetic fixture data. Never send this database to an LLM or UI."""
        encoded = self._exec(
            "ruby",
            "-rbase64",
            "-e",
            "print Base64.strict_encode64(File.binread('/tmp/legacylift-baseline.sqlite3'))",
        )
        return base64.b64decode(encoded, validate=True)

    def actor_tokens(self) -> dict[str, str]:
        return json.loads(
            self._exec("ruby", "-e", "print File.read('/tmp/legacylift-actors.json')")
        )

    def describe(self) -> dict[str, Any]:
        inspected = json.loads(self._run(["inspect", self.container_id or self.name]))[0]
        host = inspected["HostConfig"]
        versions = json.loads(
            self._exec(
                "ruby",
                "-rjson",
                "-rrails",
                "-e",
                "puts JSON.generate({ruby: RUBY_VERSION, rails: Rails.version})",
            )
        )
        return {
            "profile": "redmine-4.2.10",
            "image": REDMINE_IMAGE,
            "fixture_image": self.image,
            "image_id": inspected["Image"],
            "source_commit": REDMINE_SOURCE_COMMIT,
            "versions": versions,
            "network": host["NetworkMode"],
            "read_only_root": host["ReadonlyRootfs"],
            "user": inspected["Config"]["User"],
            "memory_limit_bytes": host["Memory"],
            "cpu_limit": host["NanoCpus"],
            "pid_limit": host["PidsLimit"],
            "capabilities_dropped": host["CapDrop"],
            "published_ports": host["PortBindings"] or {},
            "fixture_clock": "2026-01-15T12:00:00Z; advanced per request by the trusted driver",
            "host_api_keys_passed": False,
        }

    def stop(self) -> None:
        if self.container_id:
            self._run(["rm", "--force", self.container_id])
            self.container_id = None

    def __enter__(self) -> RedmineReference:
        self.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop()
