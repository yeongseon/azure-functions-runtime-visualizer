"""Structural guard: only the regexes module may import ``re`` (PRD R1).

Centralizing every log-shape assumption in one file is the project's core
format-drift mitigation; this test fails loudly if regex logic leaks into any
other parser stage.
"""

from __future__ import annotations

from pathlib import Path

PARSER_DIR = Path(__file__).resolve().parent.parent / "src" / "funcviz" / "parser"


def _imports_re(source: str) -> bool:
    for raw in source.splitlines():
        line = raw.strip()
        if line in ("import re", "import re as re"):
            return True
        if line.startswith(("import re ", "import re,", "from re import", "from re.")):
            return True
    return False


def test_only_regexes_module_imports_re():
    offenders = [
        path.name
        for path in sorted(PARSER_DIR.glob("*.py"))
        if path.name != "regexes.py" and _imports_re(path.read_text())
    ]
    assert offenders == []
