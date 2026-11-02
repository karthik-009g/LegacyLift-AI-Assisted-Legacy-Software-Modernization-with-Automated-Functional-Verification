"""Best-effort static inspection of supported Python source patterns."""

from .ast_analyzer import analyze_paths
from .storage import write_analysis_report

__all__ = ["analyze_paths", "write_analysis_report"]
