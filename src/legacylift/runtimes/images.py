"""Only trusted Dockerfiles; candidate text is copied, never run during builds."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path


def build_image(
    dockerfile: str, files: dict[str, bytes], *, prefix: str, install_dependencies: bool = False
) -> str:
    digest = hashlib.sha256(dockerfile.encode())
    for name, data in sorted(files.items()):
        digest.update(name.encode() + b"\0" + data)
    tag = f"legacylift-{prefix}:{digest.hexdigest()[:20]}"
    inspected = subprocess.run(
        ["docker", "image", "inspect", tag], capture_output=True, timeout=30, check=False
    )
    if inspected.returncode == 0:
        return tag
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, data in {"Dockerfile": dockerfile.encode(), **files}.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), 0o444, 0
            archive.addfile(info, io.BytesIO(data))
    completed = subprocess.run(
        [
            "docker",
            "build",
            "--network=default" if install_dependencies else "--network=none",
            "--pull=false",
            "--tag",
            tag,
            "-",
        ],
        input=stream.getvalue(),
        capture_output=True,
        timeout=300,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            "Trusted runtime image build failed: "
            + completed.stderr.decode(errors="replace")[-1800:]
        )
    result = subprocess.run(
        ["docker", "image", "inspect", tag], capture_output=True, timeout=30, check=True
    )
    json.loads(result.stdout)  # Ensure inspect returned valid metadata.
    return tag


def reference_image(base: str, assets: Path, *, base_image_id: str) -> str:
    if "@sha256:" not in base or not base_image_id.startswith("sha256:"):
        raise ValueError("reference image requires a digest-pinned, verified base image")
    digest = base.rsplit("@", 1)[1].removeprefix("sha256:")
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError("reference image digest is malformed")
    local_base = f"legacylift-redmine-base:{digest}"
    tagged = subprocess.run(
        ["docker", "image", "tag", base_image_id, local_base],
        capture_output=True,
        timeout=30,
        check=False,
    )
    if tagged.returncode:
        raise RuntimeError(
            "Could not tag the verified local Redmine base image: "
            + tagged.stderr.decode(errors="replace")[-1200:]
        )
    return build_image(
        f"FROM {local_base}\nCOPY assets/ /legacylift/\n"
        "COPY assets/redmine_database.yml /usr/src/redmine/config/database.yml\n"
        "COPY assets/redmine_secrets.yml /usr/src/redmine/config/secrets.yml\n",
        {
            f"assets/{path.name}": path.read_bytes()
            for path in sorted(assets.glob("*"))
            if path.suffix in {".rb", ".yml"}
        },
        prefix="reference",
    )
