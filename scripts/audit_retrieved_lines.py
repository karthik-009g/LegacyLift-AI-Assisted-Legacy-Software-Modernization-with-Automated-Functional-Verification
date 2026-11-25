"""Measure pinned source lines that survive actual guidance-only prompt packing."""

import argparse
import json
from pathlib import Path

from legacylift.modernization import model_profiles
from legacylift.modernization.contracts import canonical_hash
from legacylift.modernization.generation import build_context, prompt_for
from legacylift.modernization.repository import verify_source_tree
from legacylift.runtimes.redmine import REDMINE_SOURCE_COMMIT

# Select spans from the public source by behavior, before measuring the profiles.
SOURCE_TARGETS = {
    "create": (
        ("priority_default", "app/models/issue.rb", 225, 225),
        ("default_lookup", "app/models/enumeration.rb", 44, 52),
        ("tracker_fallback", "app/models/issue.rb", 583, 592),
        ("issue_associations", "app/views/issues/show.api.rsb", 3, 7),
    ),
    "read": (
        ("find_visible_issue", "app/controllers/application_controller.rb", 378, 386),
        ("author_display", "app/views/issues/show.api.rsb", 7, 7),
        ("issue_timestamps", "app/views/issues/show.api.rsb", 28, 30),
        ("journal_fields", "app/views/issues/show.api.rsb", 60, 61),
    ),
    "update": (
        ("journal_initialization", "app/controllers/issues_controller.rb", 524, 525),
        ("status_assignment", "app/models/issue.rb", 594, 602),
        ("journal_persistence", "app/models/issue.rb", 1995, 1999),
    ),
}


def audit(workspace: Path) -> dict:
    repo = workspace / "repositories" / REDMINE_SOURCE_COMMIT
    provenance = json.loads(repo.with_suffix(".json").read_text(encoding="utf-8"))
    if provenance.get("commit") != REDMINE_SOURCE_COMMIT:
        raise ValueError("source provenance commit differs")
    integrity = verify_source_tree(repo, provenance)
    files = {
        path: (repo / path).read_text(encoding="utf-8").splitlines()
        for targets in SOURCE_TARGETS.values()
        for _, path, _, _ in targets
    }
    variants = []
    for provider in ("groq", "gemini"):
        for workflow, targets in SOURCE_TARGETS.items():
            context = build_context(
                workspace, workflow, "hybrid", profile=model_profiles.for_provider(provider)
            )
            prompt = prompt_for(context)
            packet = json.loads(prompt.split("EVIDENCE_JSON:\n", 1)[1])
            paths = {chunk["evidence_id"]: chunk["path"] for chunk in context["source"]}
            coverage = {path: set() for path in files}
            for chunk in packet.get("source", []):
                path = paths[chunk["evidence_id"]]
                if path not in files:
                    continue
                start, end = chunk["lines"]
                expected = files[path][start - 1 : end]
                actual = chunk["text"].splitlines()
                # Tree-sitter method nodes can start after the first line's indentation.
                if (
                    not expected
                    or not actual
                    or (actual[0].lstrip() != expected[0].lstrip() or actual[1:] != expected[1:])
                ):
                    raise ValueError(f"outbound excerpt differs from pinned source: {path}:{start}")
                coverage[path].update(range(start, end + 1))
            rows = []
            for name, path, start, end in targets:
                target_lines = set(range(start, end + 1))
                missing = sorted(target_lines - coverage[path])
                rows.append(
                    {
                        "target": name,
                        "path": path,
                        "span": [start, end],
                        "missing_lines": missing,
                        "complete": not missing,
                        "line_text_sha256": canonical_hash(files[path][start - 1 : end]),
                    }
                )
            variants.append(
                {
                    "provider": provider,
                    "workflow": workflow,
                    "prompt_sha256": canonical_hash(prompt),
                    "fully_retained": sum(row["complete"] for row in rows),
                    "targets": rows,
                }
            )
    return {
        "scope": "developer-selected pinned source spans in actual hybrid prompt excerpts",
        "source_commit": REDMINE_SOURCE_COMMIT,
        "source_tree_sha256": integrity["source_tree_sha256"],
        "target_spec_sha256": canonical_hash(SOURCE_TARGETS),
        "model_requests": 0,
        "held_out_read": False,
        "variants": variants,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path(".legacylift"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.home)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as file:
        file.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    for row in report["variants"]:
        print(row["provider"], row["workflow"], row["fully_retained"], "/", len(row["targets"]))
