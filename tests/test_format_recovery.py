"""Recover narrow transport quoting defects without rewriting Python string data."""

import ast

import pytest

from legacylift.modernization.contracts import canonical_hash
from legacylift.modernization.format_recovery import recover_fstring_indices


def test_escaped_fstring_indexes_recover_as_literal_keys_with_provenance():
    source = 'name = f"{actor[\\"firstname\\"]} {actor[\\"lastname\\"]}"\n'
    expected = "name = f\"{actor['firstname']} {actor['lastname']}\"\n"
    actual, report = recover_fstring_indices(source)
    assert actual == expected
    assert ast.dump(ast.parse(actual)) == ast.dump(ast.parse(expected))
    assert report["raw_source_sha256"] == canonical_hash(source)
    assert report["normalized_source_sha256"] == canonical_hash(expected)
    assert report["semantics_verified"] is False


def test_partial_indented_patch_retains_indentation_and_unrelated_escaped_literals():
    source = '        name = f"{actor[\\"firstname\\"]}"\n        quoted = "a\\"b"\n'
    actual, report = recover_fstring_indices(source)
    assert actual.startswith("        name = f\"{actor['firstname']}\"\n")
    assert actual.splitlines(keepends=True)[1] == source.splitlines(keepends=True)[1]
    assert report is not None


@pytest.mark.parametrize(
    "source",
    [
        "name = f\"{actor['firstname']}\"\n",
        'data = "{actor[\\"firstname\\"]}"\ninvalid =\n',
        'data = f"{{actor[\\"firstname\\"]}}"\ninvalid =\n',
        'data = f"{str(\'{actor[\\"firstname\\"]}\')}"\n',
        'data = f"{actor[\\"firstname\\"]!s}"\n',
    ],
)
def test_valid_source_literal_data_and_complex_expressions_remain_unchanged(source):
    assert recover_fstring_indices(source) == (source, None)
