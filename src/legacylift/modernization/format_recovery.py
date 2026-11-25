"""Conservative lexical recovery for a measured model JSON/Python quoting error.

This transforms untrusted proposed code, never executes it or certifies its semantics.
Every recovered proposal still requires normal static and independent runtime checks.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize

from .contracts import canonical_hash

POLICY = "fstring-index-quotes-v1"
_PREFIX = re.compile(r"(?i)^(?:fr|rf|f)(?P<quote>['\"])")
_INDEX = re.compile(
    r"(?<!\{)\{(?P<name>[A-Za-z_]\w*)\[(?P<quote>\\['\"])"
    r"(?P<key>[A-Za-z_]\w*)(?P=quote)\]\}(?!\})"
)


def recover_fstring_indices(source: str) -> tuple[str, dict | None]:
    """Repair only escaped literal dictionary keys in lexed f-string expressions.

    Valid Python is untouched. No general JSON unescaping, arbitrary quote replacement,
    parser-error suppression or candidate execution occurs. Partial edit snippets may
    remain incomplete; the assembled source must still pass the target parser policy.
    """
    try:
        ast.parse(source)
    except SyntaxError:
        pass
    else:
        return source, None
    offsets = [0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    edits = []
    stream = tokenize.generate_tokens(io.StringIO(source).readline)
    try:
        for token in stream:
            prefix = _PREFIX.match(token.string) if token.type == tokenize.STRING else None
            if prefix is None:
                continue
            delimiter = prefix["quote"]
            if token.string.startswith(delimiter * 3, prefix.start("quote")):
                delimiter *= 3
            body = token.string[prefix.start("quote") + len(delimiter) : -len(delimiter)]
            remainder = _INDEX.sub("", body).replace("{{", "").replace("}}", "")
            if "{" in remainder or "}" in remainder:
                # Avoid nested expressions and quoted strings inside other expressions.
                continue
            quote = "'" if prefix["quote"] == '"' else '"'
            replacement = _INDEX.sub(
                lambda match: "{" + match["name"] + "[" + quote + match["key"] + quote + "]}",
                token.string,
            )
            if replacement != token.string:
                edits.append(
                    (
                        offsets[token.start[0] - 1] + token.start[1],
                        offsets[token.end[0] - 1] + token.end[1],
                        replacement,
                        token.start[0],
                    )
                )
    except (tokenize.TokenError, IndentationError):
        # Only already lexed string tokens are eligible; malformed remainder is retained.
        pass
    if not edits:
        return source, None
    normalized = source
    for start, end, replacement, _ in reversed(edits):
        normalized = normalized[:start] + replacement + normalized[end:]
    return normalized, {
        "policy": POLICY,
        "raw_source_sha256": canonical_hash(source),
        "normalized_source_sha256": canonical_hash(normalized),
        "token_lines": [line for _, _, _, line in edits],
        "semantics_verified": False,
    }
