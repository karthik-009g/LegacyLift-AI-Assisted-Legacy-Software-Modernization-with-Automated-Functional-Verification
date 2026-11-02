"""Serialize static analysis findings as stable JSON."""

from __future__ import annotations

import json
from pathlib import Path

from .models import AnalysisReport


def write_analysis_report(report: AnalysisReport, output_path: str | Path) -> Path:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(report.to_dict(), indent=2, sort_keys=True, ensure_ascii=False)
    destination.write_text(content + "\n", encoding="utf-8")
    return destination
