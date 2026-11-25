"""Trusted loopback driver. This file contains no expected results or scenarios."""

import json
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

if sys.argv[1] == "snapshot":
    connection = sqlite3.connect("file:/state/candidate.sqlite3?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    print(
        json.dumps(
            {
                table: [
                    dict(row) for row in connection.execute(f'SELECT * FROM "{table}" ORDER BY id')
                ]
                for table in ("issues", "journals", "journal_details")
            }
        )
    )
elif sys.argv[1] == "reset":
    source = sqlite3.connect("file:/state/baseline.sqlite3?mode=ro", uri=True)
    destination = sqlite3.connect("/state/candidate.sqlite3")
    source.backup(destination)
    destination.close()
    source.close()
    Path("/state/clock").write_text("1768478400")
else:
    request = json.load(sys.stdin)
    path = request["path"]
    if not path.startswith("/") or path.startswith("//") or any(ord(c) < 32 for c in path):
        raise ValueError("local paths only")
    if request.get("fixture_epoch"):
        Path("/state/clock").write_text(str(int(request["fixture_epoch"])))
    headers = {"Accept": "application/json"}
    if request["actor"] != "anonymous":
        headers["X-Redmine-API-Key"] = json.loads(Path("/state/actors.json").read_text())[
            request["actor"]
        ]
    body = request.get("json_body")
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        "http://127.0.0.1:3000" + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
        method=request["method"],
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        response = opener.open(req, timeout=15)
    except urllib.error.HTTPError as error:
        response = error
    raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("candidate response exceeds limit")
    try:
        parsed = json.loads(raw) if raw else None
    except (ValueError, UnicodeDecodeError):
        parsed = None
    print(
        json.dumps(
            {
                "status": response.status,
                "headers": {
                    k.lower(): v
                    for k, v in response.headers.items()
                    if k.lower() in {"content-type", "cache-control", "location"}
                },
                "json": parsed,
                "body_bytes": len(raw),
            }
        )
    )
