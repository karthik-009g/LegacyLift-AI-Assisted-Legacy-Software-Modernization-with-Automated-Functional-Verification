"""Measured container controls, separate from application compatibility/security."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager

from legacylift.runtimes.python_target import PythonTarget

ASSESSMENT_VERSION = "1.0"
HOST_SENTINEL = "LEGACYLIFT_ISOLATION_HOST_SECRET"
PROBE_SOURCE = r"""
import errno, json, os, socket, uuid
from pathlib import Path

status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines())
result = {
    'uid': os.getuid(),
    'effective_capabilities': status['CapEff'].strip(),
    'no_new_privileges': status['NoNewPrivs'].strip(),
    'seccomp': status['Seccomp'].strip(),
    'credential_environment_names': sorted(name for name in os.environ if
        name == 'LEGACYLIFT_ISOLATION_HOST_SECRET' or name in {
            'GROQ_API_KEY', 'GEMINI_API_KEY', 'OPENROUTER_API_KEY',
            'GOOGLE_API_KEY', 'OPENAI_API_KEY',
            'ANTHROPIC_API_KEY', 'GOOGLE_APPLICATION_CREDENTIALS'
        } or name.startswith(('AWS_', 'AZURE_'))),
    'visible_sensitive_paths': [path for path in (
        '/var/run/docker.sock', '/run/docker.sock', '/candidate/.env',
        '/app/.env', '/study/oracle.json', '/oracle.json'
    ) if Path(path).exists()],
}
probe = Path('/candidate/.isolation-probe-' + uuid.uuid4().hex)
try:
    probe.write_bytes(b'probe')
    result['candidate_directory_write_errno'] = 0
    probe.unlink()
except OSError as error:
    result['candidate_directory_write_errno'] = error.errno
state = Path('/state/.isolation-probe-' + uuid.uuid4().hex)
try:
    state.write_bytes(b'disposable state')
    result['state_write_succeeded'] = state.read_bytes() == b'disposable state'
finally:
    state.unlink(missing_ok=True)
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
    connection.settimeout(1)
    try:
        # TEST-NET address: no real service or user data is contacted.
        connection.connect(('198.51.100.1', 9))
        result['outbound_connect_errno'] = 0
    except OSError as error:
        result['outbound_connect_errno'] = error.errno
result['cgroup'] = {
    name: Path('/sys/fs/cgroup/' + name).read_text().strip()
    for name in ('memory.max', 'pids.max', 'cpu.max')
}
print(json.dumps(result))
"""

TRUSTED_PROBE_APP = (
    "from fastapi import FastAPI, Response\n"
    "app = FastAPI()\n"
    "@app.get('/issues/{issue_id}.json')\n"
    "def show(issue_id: int):\n"
    "    return Response(status_code=404)\n"
)


def evaluate_isolation_observations(inspected: dict, probe: dict) -> dict:
    """Fail closed if an inspection/probe is absent or a declared control is weaker."""
    host = inspected.get("HostConfig", {})
    config = inspected.get("Config", {})
    network = inspected.get("NetworkSettings", {})
    cgroup = probe.get("cgroup", {})
    try:
        quota, period = map(int, cgroup.get("cpu.max", "").split())
        cgroup_bounded = (
            0 < int(cgroup.get("memory.max", 0)) <= 768 * 1024**2
            and 0 < int(cgroup.get("pids.max", 0)) <= 96
            and 0 < quota <= period
        )
    except (TypeError, ValueError):
        cgroup_bounded = False
    checks = {
        "network_namespace_none": host.get("NetworkMode") == "none",
        "no_published_ports": not host.get("PortBindings")
        and not any(network.get("Ports", {}).values()),
        "no_host_or_volume_mounts": not host.get("Binds")
        and not host.get("VolumesFrom")
        and all(
            mount.get("Type") == "tmpfs" and mount.get("Destination") in {"/state", "/tmp"}
            for mount in inspected.get("Mounts", [])
        ),
        "read_only_root": host.get("ReadonlyRootfs") is True,
        "non_root_user": config.get("User") == "999:999" and probe.get("uid") == 999,
        "not_privileged": host.get("Privileged") is False,
        "capabilities_dropped": "ALL" in host.get("CapDrop", [])
        and not host.get("CapAdd")
        and probe.get("effective_capabilities") == "0000000000000000",
        "no_new_privileges": "no-new-privileges" in host.get("SecurityOpt", [])
        and probe.get("no_new_privileges") == "1",
        "seccomp_filter_active": probe.get("seccomp") == "2",
        "resource_limits_configured": 0 < host.get("Memory", 0) <= 768 * 1024**2
        and 0 < host.get("PidsLimit", 0) <= 96
        and 0 < host.get("NanoCpus", 0) <= 1_000_000_000,
        "resource_limits_observed": cgroup_bounded,
        "credential_environment_absent": probe.get("credential_environment_names") == [],
        "sensitive_paths_absent": probe.get("visible_sensitive_paths") == [],
        # Linux EROFS and ENETUNREACH: a generic exception/timeout is not proof.
        "candidate_directory_write_denied": probe.get("candidate_directory_write_errno") == 30,
        "outbound_connection_unroutable": probe.get("outbound_connect_errno") == 101,
        "disposable_state_writable": probe.get("state_write_succeeded") is True,
    }
    return {
        "assessment_version": ASSESSMENT_VERSION,
        "status": "passed" if all(checks.values()) else "failed",
        "scope": "candidate_container_controls",
        "certified_secure": False,
        "model_requests": 0,
        "held_out_observations_read": False,
        "checks": checks,
        "probe_observations": probe,
        "image_id": inspected.get("Image"),
        "probe_sha256": hashlib.sha256(PROBE_SOURCE.encode()).hexdigest(),
        "limitations": [
            "Trusted diagnostic app and a new synthetic database; not a generated migration.",
            "Checks controls and simple negative probes, not a container escape penetration test.",
            "Docker daemon, host kernel, controller and pinned images remain trusted.",
            "Dependency vulnerabilities and application authorization/SQL logic are separate.",
            "Finite resource limits were inspected; destructive exhaustion was not attempted.",
            "Candidate and driver share writable synthetic state; this is not process separation.",
        ],
    }


@contextmanager
def _host_sentinel():
    previous = os.environ.get(HOST_SENTINEL)
    os.environ[HOST_SENTINEL] = uuid.uuid4().hex
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(HOST_SENTINEL, None)
        else:
            os.environ[HOST_SENTINEL] = previous


def assess_runtime_isolation() -> dict:
    """Start only an owned trusted diagnostic container; never read project fixtures/keys."""
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE TABLE isolation_probe(value TEXT)")
        database = connection.serialize()
    actors = {"alice": "assessment-only-" + uuid.uuid4().hex}
    with _host_sentinel(), PythonTarget(TRUSTED_PROBE_APP, database, actors, timeout=60) as target:
        inspected = json.loads(target._run(["inspect", target.container_id]))[0]
        probe = json.loads(
            target._exec(
                "python",
                "-I",
                "-c",
                "import sys; exec(compile(sys.stdin.read(), '<isolation-probe>', 'exec'))",
                payload=PROBE_SOURCE,
            )
        )
        return evaluate_isolation_observations(inspected, probe)
