"""Literal Redmine access-control declarations, parsed without executing Ruby."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import tree_sitter_ruby
from tree_sitter import Language, Parser

from legacylift.runtimes.redmine import REDMINE_SOURCE_COMMIT

from .repository import native_source_path, verify_source_tree


def _symbol(node) -> str | None:
    if node is None or node.type not in {"simple_symbol", "hash_key_symbol"}:
        return None
    name = node.text.decode("utf-8").strip(":")
    return name if re.fullmatch(r"[a-z][a-z0-9_]*", name) else None


def extract_access_control(source: bytes, *, path: str = "lib/redmine.rb") -> dict:
    parser = Parser(Language(tree_sitter_ruby.language()))
    tree = parser.parse(source)
    file_hash = hashlib.sha256(source).hexdigest()
    bindings, unknowns = [], []

    def declaration(node):
        arguments = node.child_by_field_name("arguments")
        values = arguments.named_children if arguments is not None else []
        permission = _symbol(values[0]) if values else None
        routes = values[1] if len(values) > 1 else None
        if permission is None or routes is None or routes.type != "hash":
            unknowns.append(
                f"Nonliteral permission declaration at {path}:{node.start_point.row + 1}"
            )
            return
        controller_actions = {}
        for pair in routes.named_children:
            controller = _symbol(pair.child_by_field_name("key"))
            value = pair.child_by_field_name("value")
            actions = (
                value.named_children if value is not None and value.type == "array" else [value]
            )
            names = [_symbol(action) for action in actions]
            if not controller or not names or any(name is None for name in names):
                unknowns.append(
                    f"Nonliteral controller/action mapping at {path}:{pair.start_point.row + 1}"
                )
                if controller is None:
                    return
                controller_actions.pop(controller, None)
                continue
            controller_actions[controller] = names
        if not controller_actions:
            return
        start, end = node.start_point.row + 1, node.end_point.row + 1
        text = source[node.start_byte : node.end_byte]
        bindings.append(
            {
                "evidence_id": f"ruby-permission:{path}:{start}:{end}",
                "kind": "literal_access_control_declaration",
                "permission": permission,
                "controller_actions": controller_actions,
                "path": path,
                "start_line": start,
                "end_line": end,
                "sha256": hashlib.sha256(text).hexdigest(),
                "file_sha256": file_hash,
                "text": text.decode("utf-8"),
            }
        )

    def walk(node, receivers):
        if node.type in {"method", "singleton_method", "class", "module"}:
            receivers = set()
        if node.type in {"assignment", "operator_assignment"}:
            left = node.child_by_field_name("left")
            if left is not None and left.type == "identifier":
                receivers.discard(left.text.decode("utf-8"))
        method = node.child_by_field_name("method") if node.type == "call" else None
        receiver = node.child_by_field_name("receiver") if node.type == "call" else None
        method_name = method.text.decode("utf-8") if method is not None else None
        receiver_name = receiver.text.decode("utf-8") if receiver is not None else None
        known_receiver = (
            receiver is not None and receiver.type == "identifier" and (receiver_name in receivers)
        )
        if method_name == "permission" and known_receiver:
            declaration(node)
        block = node.child_by_field_name("block") if node.type == "call" else None
        map_block = (method_name == "map" and receiver_name == "Redmine::AccessControl") or (
            method_name == "project_module" and known_receiver
        )
        for child in node.named_children:
            if child == block:
                parameters = block.child_by_field_name("parameters")
                names = parameters.named_children if parameters is not None else []
                shadowed = {name.text.decode("utf-8") for name in names}
                nested = receivers - shadowed
                if any(name.type != "identifier" for name in names):
                    nested = set()
                if map_block and len(names) == 1 and names[0].type == "identifier":
                    nested.add(names[0].text.decode("utf-8"))
                walk(child, nested)
                # Closures can rebind captured receivers. Their parameters stay local.
                receivers.intersection_update(nested | shadowed)
            else:
                walk(child, receivers)

    if not tree.root_node.has_error:
        walk(tree.root_node, set())
    else:
        unknowns.append(f"Ruby syntax errors prevent access-control extraction from {path}")
    return {
        "version": "literal-redmine-access-control-1",
        "parser": "tree-sitter-ruby",
        "status": "parse_error" if tree.root_node.has_error else "parsed",
        "file_sha256": file_hash,
        "bindings": bindings,
        "unknowns": unknowns,
        "limits": [
            "Declarations are source facts, not observations of authorization decisions.",
            "Object-level permissions, controller filters and dynamic Ruby behavior need "
            "additional evidence and independent replay.",
            "Only literal symbols and explicit route hashes in recognized AccessControl.map "
            "and project_module blocks are extracted.",
        ],
    }


def permission_evidence(workspace: Path, actions: set[str]) -> dict:
    """Read verified public source without replacing the cached or sealed study evidence."""
    root = native_source_path(workspace / "repositories" / REDMINE_SOURCE_COMMIT)
    if not root.exists():
        return {
            "status": "source_unavailable",
            "bindings": [],
            "unknowns": ["Access-control declaration source is unavailable in this workspace."],
        }
    provenance_path = root.parent / f"{REDMINE_SOURCE_COMMIT}.json"
    if provenance_path.is_symlink():
        raise ValueError("source provenance must not be a symbolic link")
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if provenance.get("commit") != REDMINE_SOURCE_COMMIT:
        raise ValueError("access-control source commit differs from the selected reference")
    verified = verify_source_tree(root, provenance)
    name = "lib/redmine.rb"
    expected = next((f for f in verified["file_manifest"] if f["path"] == name), None)
    if expected is None:
        raise ValueError("access-control source is absent from the integrity manifest")
    raw = (root / name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected["sha256"]:
        raise ValueError("access-control source changed after integrity verification")
    report = extract_access_control(raw, path=name)
    report["literal_route_declaration_count"] = len(report["bindings"])
    report["source_commit"] = REDMINE_SOURCE_COMMIT
    report["source_tree_sha256"] = verified["source_tree_sha256"]
    report["bindings"] = [
        fact
        for fact in report["bindings"]
        if actions.intersection(fact["controller_actions"].get("issues", []))
    ]
    return report
