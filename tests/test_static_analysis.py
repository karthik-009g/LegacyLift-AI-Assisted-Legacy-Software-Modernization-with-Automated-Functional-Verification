from __future__ import annotations

from pathlib import Path

from legacylift.static_analysis import analyze_paths, write_analysis_report


def test_analyzer_finds_literal_routes_and_session_database_references():
    project_root = Path(__file__).parents[1]
    report = analyze_paths(
        [project_root / "src" / "legacylift" / "legacy_app"],
        root=project_root,
    )

    route_map = {(route.method, route.path): route.function for route in report.routes}
    assert route_map == {
        ("POST", "/session"): "start_test_session",
        ("POST", "/tickets"): "create_ticket",
        ("GET", "/tickets/<int:ticket_id>"): "get_ticket",
        ("PATCH", "/tickets/<int:ticket_id>/status"): "update_ticket_status",
    }
    get_ticket = next(function for function in report.functions if function.name == "get_ticket")
    assert get_ticket.session_references == ("session",)
    assert "get_db" in get_ticket.calls
    assert any(operation.endswith(".execute") for operation in get_ticket.database_operations)
    assert "flask" in report.imports
    assert report.issues == ()
    assert report.limitations


def test_analyzer_reports_syntax_errors_without_losing_other_findings(tmp_path):
    (tmp_path / "routes.py").write_text(
        "@app.get('/ok')\ndef ok():\n    return 'ok'\n",
        encoding="utf-8",
    )
    (tmp_path / "broken.py").write_text("def broken(:\n    pass\n", encoding="utf-8")

    report = analyze_paths([tmp_path], root=tmp_path)

    assert {(route.method, route.path) for route in report.routes} == {("GET", "/ok")}
    assert len(report.issues) == 1
    assert report.issues[0].source_file == "broken.py"
    assert report.issues[0].line == 1


def test_checked_in_analysis_report_matches_current_source(tmp_path):
    project_root = Path(__file__).parents[1]
    report = analyze_paths(
        [project_root / "src" / "legacylift" / "legacy_app"],
        root=project_root,
    )
    generated = write_analysis_report(report, tmp_path / "current.json")
    checked_in = project_root / "artifacts" / "static" / "legacy_analysis.json"

    assert generated.read_bytes() == checked_in.read_bytes()
