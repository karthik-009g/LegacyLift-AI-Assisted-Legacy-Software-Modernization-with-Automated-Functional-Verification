"""Public advisory lookup must use exact versions and preserve incomplete coverage."""

import importlib.util
from pathlib import Path

import httpx
import pytest

spec = importlib.util.spec_from_file_location(
    "dependency_audit_script", Path(__file__).parents[1] / "scripts/audit_python_dependencies.py"
)
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)


def test_advisory_lookup_deduplicates_pins_and_preserves_each_lock(tmp_path):
    first, second = tmp_path / "one.lock", tmp_path / "two.lock"
    first.write_text("Example_Package==1.2.3\n", encoding="utf-8")
    second.write_text("example-package==1.2.3\n", encoding="utf-8")
    requests = []

    def reply(request):
        requests.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "info": {"name": "example-package", "version": "1.2.3"},
                "vulnerabilities": [
                    {
                        "id": "PYSEC-synthetic",
                        "fixed_in": ["1.2.4"],
                        "link": "https://example.test/advisory",
                    },
                    {"id": "withdrawn-synthetic", "withdrawn": "2026-01-01"},
                ],
            },
        )

    report = script.audit_locks([first, second], transport=httpx.MockTransport(reply))
    assert requests == ["https://pypi.org/pypi/example-package/1.2.3/json"]
    assert report["status"] == "findings" and len(report["findings"]) == 1
    assert len(report["findings"][0]["locks"]) == 2
    assert report["findings"][0]["fixed_in"] == ["1.2.4"]
    assert not report["certified_secure"]


@pytest.mark.parametrize(
    "pin", ["package>=1.0", "package==1.*", "package @ https://example.test/pkg.whl"]
)
def test_unpinned_input_is_rejected_before_any_lookup(tmp_path, pin):
    path = tmp_path / "unsafe.lock"
    path.write_text(pin + "\n", encoding="utf-8")
    transport = httpx.MockTransport(lambda request: pytest.fail("unvalidated request"))
    with pytest.raises(ValueError, match="exact public"):
        script.audit_locks([path], transport=transport)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503),
        httpx.Response(
            200, json={"info": {"name": "package", "version": "2.0"}, "vulnerabilities": []}
        ),
        httpx.Response(200, json={"info": {"name": "package", "version": "1.0"}}),
        httpx.Response(
            200,
            json={"info": {"name": "package", "version": "1.0"}, "vulnerabilities": [{}]},
        ),
    ],
)
def test_failed_or_mismatched_metadata_is_incomplete_not_clean(tmp_path, response):
    path = tmp_path / "pins.lock"
    path.write_text("package==1.0\n", encoding="utf-8")
    report = script.audit_locks([path], transport=httpx.MockTransport(lambda request: response))
    assert report["status"] == "incomplete"
    assert report["errors"] and report["checked_package_versions"] == 0
