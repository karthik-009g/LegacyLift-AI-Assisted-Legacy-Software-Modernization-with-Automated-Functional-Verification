"""Exact, bounded candidate-source views and validation of visible edit ranges."""

from __future__ import annotations

import json
import re

from .contracts import canonical_hash


def select_source_windows(
    source: str,
    anchors: list[int],
    *,
    byte_budget: int,
    compact_first: bool = False,
    first_line: int = 1,
    max_window_lines: int | None = None,
) -> dict | None:
    lines = source.splitlines(keepends=True)
    if not 1 <= first_line <= len(lines):
        return None
    anchors = list(
        dict.fromkeys(
            min(line, len(lines))
            for line in anchors
            if type(line) is int and first_line <= line <= len(lines) + 1
        )
    ) or [first_line, len(lines)]
    definitions = [
        number
        for number, line in enumerate(lines, 1)
        if number >= first_line and re.match(r"\s*(?:async\s+def|def|class)\s+", line)
    ]
    relevant_definitions = [
        max((line for line in definitions if line <= anchor), default=first_line)
        for anchor in anchors
    ]
    interfaces = [
        {"line": line, "definition_prefix": lines[line - 1].rstrip()[:160]}
        for line in dict.fromkeys([*relevant_definitions, *definitions])
        if line in definitions
    ][:24]

    def packet(ranges):
        return {
            "version": "candidate-source-windows-1",
            "source_sha256": canonical_hash(source),
            "total_lines": len(lines),
            "omitted_lines": len(lines) - sum(end - start + 1 for start, end in ranges),
            "definition_prefixes": interfaces,
            "windows": [
                {"start_line": start, "end_line": end, "text": "".join(lines[start - 1 : end])}
                for start, end in ranges
            ],
        }

    # Code windows have priority over optional definition-line context.
    while (
        interfaces and len(json.dumps(packet([]), ensure_ascii=False).encode()) > byte_budget // 3
    ):
        interfaces.pop()
    candidates = []
    if compact_first:
        # Cover the selected lines before a large function consumes the window budget.
        candidates.extend(
            (max(first_line, line - 2), min(len(lines), line + 2)) for line in anchors
        )
        candidates.extend((line, line) for line in anchors)
    for anchor, definition in zip(anchors, relevant_definitions, strict=True):
        candidates.append((definition, min(len(lines), anchor + 12)))
        candidates.append((max(first_line, anchor - 16), min(len(lines), anchor + 16)))
        candidates.append((max(first_line, anchor - 4), min(len(lines), anchor + 4)))
    candidates.append((first_line, min(first_line + 23, len(lines))))
    selected = []
    for candidate in dict.fromkeys(candidates):
        merged = []
        for start, end in sorted([*selected, candidate]):
            if merged and start <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        if max_window_lines is not None and any(
            end - start + 1 > max_window_lines for start, end in merged
        ):
            continue
        if (
            len(json.dumps(packet(merged), ensure_ascii=False, separators=(",", ":")).encode())
            <= byte_budget
        ):
            selected = merged
    return packet(selected) if selected else None


def visible_source_ranges(source: str, source_view: dict) -> list[tuple[int, int]]:
    """Bind visible text to the full source before using character offsets for edits."""
    if source_view.get("source_sha256") != canonical_hash(source):
        raise ValueError("repair windows differ from the previous source checksum")
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    ranges = []
    for window in source_view.get("windows", []):
        if not isinstance(window, dict):
            raise ValueError("invalid source window")
        start, end = window.get("start_line"), window.get("end_line")
        if type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(lines):
            raise ValueError("invalid source window line bounds")
        if "".join(lines[start - 1 : end]) != window.get("text"):
            raise ValueError("repair window text differs from the previous source")
        ranges.append((offsets[start - 1], offsets[end]))
    if not ranges:
        raise ValueError("repair source view contains no windows")
    return ranges
