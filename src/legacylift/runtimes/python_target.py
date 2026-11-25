"""Independent Python application container with an oracle-free trusted driver."""

from __future__ import annotations

import base64
import json
import time
import uuid

from .images import build_image
from .models import RuntimeRequest, RuntimeResponse
from .redmine import ASSETS, RedmineReference, RuntimeUnavailable

PYTHON_IMAGE = (
    "python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f"
)


class CandidateRejected(RuntimeError):
    """The candidate itself failed to boot; this may be repaired using guidance."""


def target_base() -> str:
    return build_image(
        f"FROM {PYTHON_IMAGE}\nCOPY requirements.lock /driver/requirements.lock\n"
        "RUN python -m pip install --no-cache-dir -r /driver/requirements.lock\n"
        "COPY candidate_proxy.py /driver/proxy.py\nWORKDIR /candidate\n"
        "ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp\n",
        {
            "requirements.lock": (ASSETS / "target-requirements.lock").read_bytes(),
            "candidate_proxy.py": (ASSETS / "candidate_proxy.py").read_bytes(),
        },
        prefix="target-base",
        install_dependencies=True,
    )


class PythonTarget(RedmineReference):
    def __init__(self, source: str, database: bytes, actors: dict[str, str], **kwargs):
        super().__init__(**kwargs)
        if len(source.encode()) > 200_000:
            raise ValueError("candidate source exceeds size bound")
        self.source, self.database, self.actors = source, database, actors
        self.name = f"legacylift-target-{uuid.uuid4().hex[:12]}"

    def start(self) -> None:
        if self.container_id:
            raise RuntimeUnavailable("candidate already started")
        base = target_base()
        self.image = build_image(
            f"FROM {base}\nCOPY app.py /candidate/app.py\n",
            {"app.py": self.source.encode()},
            prefix="candidate",
        )
        self.container_id = self._run(
            [
                "run",
                "--detach",
                "--pull=never",
                "--name",
                self.name,
                "--label",
                "io.legacylift.role=candidate",
                "--network=none",
                "--read-only",
                "--user=999:999",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--memory=768m",
                "--cpus=1",
                "--pids-limit=96",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,size=32m,mode=1777",
                "--tmpfs",
                "/state:rw,nosuid,nodev,size=64m,uid=999,gid=999,mode=0700",
                "--env",
                "DATABASE_URL=sqlite:////state/candidate.sqlite3",
                "--entrypoint",
                "sleep",
                self.image,
                "infinity",
            ]
        ).strip()
        try:
            # Payload is synthetic fixture data, not environment or provider credentials.
            self._exec(
                "python",
                "-I",
                "-c",
                "import base64,json,sys,pathlib; p=json.load(sys.stdin); "
                "d=base64.b64decode(p['database']); "
                "pathlib.Path('/state/baseline.sqlite3').write_bytes(d); "
                "pathlib.Path('/state/candidate.sqlite3').write_bytes(d); "
                "pathlib.Path('/state/clock').write_text('1768478400'); "
                "pathlib.Path('/state/actors.json').write_text(json.dumps(p['actors']))",
                payload=json.dumps(
                    {"database": base64.b64encode(self.database).decode(), "actors": self.actors}
                ),
            )
            self._exec(
                "python",
                "-I",
                "-c",
                "import subprocess; log=open('/state/server.log','wb'); "
                "subprocess.Popen(['python','-m','uvicorn','app:app','--host','127.0.0.1',"
                "'--port','3000','--no-access-log','--log-level','error'],"
                "stdout=log,stderr=log,stdin=subprocess.DEVNULL,start_new_session=True)",
            )
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    self.request(RuntimeRequest(method="GET", path="/issues/1.json", actor="alice"))
                    return  # HTTP failures are observations, not infrastructure failures.
                except RuntimeUnavailable:
                    time.sleep(0.5)
            detail = self._exec(
                "python",
                "-I",
                "-c",
                "from pathlib import Path; print(Path('/state/server.log').read_text()[-1800:])",
            )
            raise CandidateRejected("Candidate boot failed: " + detail)
        except Exception:
            self.stop()
            raise

    def request(self, request: RuntimeRequest) -> RuntimeResponse:
        output = self._exec(
            "python", "-I", "/driver/proxy.py", "request", payload=request.model_dump_json()
        )
        return RuntimeResponse.model_validate_json(output)

    def reset(self) -> None:
        self._exec("python", "-I", "/driver/proxy.py", "reset")

    def snapshot(self) -> dict:
        return json.loads(self._exec("python", "-I", "/driver/proxy.py", "snapshot"))

    def describe(self) -> dict:
        inspected = json.loads(self._run(["inspect", self.container_id]))[0]
        return {
            "profile": "python-fastapi",
            "base_image": PYTHON_IMAGE,
            "image_id": inspected["Image"],
            "network": inspected["HostConfig"]["NetworkMode"],
            "read_only_root": inspected["HostConfig"]["ReadonlyRootfs"],
            "user": inspected["Config"]["User"],
            "host_api_keys_passed": False,
            "oracle_in_image": False,
        }

    def diagnostics(self) -> str:
        detail = self._exec(
            "python",
            "-I",
            "-c",
            "from pathlib import Path; print(Path('/state/server.log').read_text()[-4000:])",
        )
        for token in self.actors.values():
            detail = detail.replace(token, "[synthetic-token-redacted]")
        return detail
