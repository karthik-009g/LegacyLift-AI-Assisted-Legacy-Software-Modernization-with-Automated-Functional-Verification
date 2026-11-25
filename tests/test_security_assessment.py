"""An isolation report must reject missing observations and weakened controls."""

import copy
import os

import pytest

from legacylift.modernization.security_assessment import (
    HOST_SENTINEL,
    _host_sentinel,
    assess_runtime_isolation,
    evaluate_isolation_observations,
)


@pytest.fixture
def observations():
    inspected = {
        "Config": {"User": "999:999"},
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "Privileged": False,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"],
            "Memory": 768 * 1024**2,
            "PidsLimit": 96,
            "NanoCpus": 1_000_000_000,
        },
        "NetworkSettings": {"Ports": {}},
        "Mounts": [],
    }
    probe = {
        "uid": 999,
        "effective_capabilities": "0000000000000000",
        "no_new_privileges": "1",
        "seccomp": "2",
        "credential_environment_names": [],
        "visible_sensitive_paths": [],
        "candidate_directory_write_errno": 30,
        "outbound_connect_errno": 101,
        "state_write_succeeded": True,
        "cgroup": {"memory.max": str(768 * 1024**2), "pids.max": "96", "cpu.max": "100000 100000"},
    }
    return inspected, probe


def test_missing_probe_cannot_support_a_pass(observations):
    inspected, probe = observations
    assert evaluate_isolation_observations(inspected, probe)["status"] == "passed"
    assert evaluate_isolation_observations(inspected, {})["status"] == "failed"
    assert evaluate_isolation_observations({}, probe)["status"] == "failed"


@pytest.mark.parametrize(
    "target,key,value",
    [
        ("host", "Binds", ["C:/sensitive:/host"]),
        ("host", "PortBindings", {"3000/tcp": [{"HostPort": "3000"}]}),
        ("host", "ReadonlyRootfs", False),
        ("host", "Privileged", True),
        ("host", "NanoCpus", 0),
        ("host", "CapAdd", ["SYS_ADMIN"]),
        ("probe", "uid", 0),
        ("probe", "seccomp", "0"),
        ("probe", "credential_environment_names", ["GROQ_API_KEY"]),
        ("probe", "visible_sensitive_paths", ["/var/run/docker.sock"]),
        ("probe", "outbound_connect_errno", None),
        ("probe", "candidate_directory_write_errno", 13),
        ("probe", "cgroup", {"memory.max": "max", "pids.max": "max", "cpu.max": "max 100000"}),
    ],
)
def test_weakened_controls_or_inconclusive_errors_fail_assessment(observations, target, key, value):
    inspected, probe = copy.deepcopy(observations)
    (inspected["HostConfig"] if target == "host" else probe)[key] = value
    report = evaluate_isolation_observations(inspected, probe)
    assert report["status"] == "failed" and not report["certified_secure"]


def test_host_sentinel_restores_existing_or_absent_environment_after_failure(monkeypatch):
    monkeypatch.setenv(HOST_SENTINEL, "previous")
    with pytest.raises(RuntimeError), _host_sentinel():
        assert os.environ[HOST_SENTINEL] != "previous"
        raise RuntimeError("diagnostic failed")
    assert os.environ[HOST_SENTINEL] == "previous"
    monkeypatch.delenv(HOST_SENTINEL)
    with _host_sentinel():
        assert HOST_SENTINEL in os.environ
    assert HOST_SENTINEL not in os.environ


@pytest.mark.skipif(
    os.environ.get("LEGACYLIFT_V2_DOCKER_SMOKE") != "1",
    reason="measured isolation assessment requires LEGACYLIFT_V2_DOCKER_SMOKE=1",
)
def test_measured_candidate_isolation_with_new_synthetic_state():
    report = assess_runtime_isolation()
    assert report["status"] == "passed", report["checks"]
    assert not report["certified_secure"]
    assert not report["held_out_observations_read"]
    assert report["model_requests"] == 0
