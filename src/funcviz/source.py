"""Post-parse source enrichment (PRD FR-6, AC6).

This module lives *outside* :mod:`funcviz.parser` on purpose. The parser is a
pure log reader with no filesystem access (see ``parser/core.py``); embedding
the executed application's source text requires reading a file, so it is done
here as a separate transformation applied *above* the parser.

The public entry point :func:`enrich_trace_from_source` reads the given source
file, embeds its text into ``trace.application.sourceText``, and — for Python
sources whose defining function can be unambiguously located — records the
``definitionLineRange`` (1-based, decorator-inclusive) used by the viewer's
source panel to highlight the executed function.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from funcviz.models import Application, Failure, Trace
from funcviz.parser.regexes import match_traceback_source_line

Warn = Callable[[str], None]


def _noop(_message: str) -> None:  # pragma: no cover - trivial default
    pass


def enrich_trace_from_source(
    trace: Trace,
    source_path: Path,
    *,
    warn: Warn | None = None,
) -> Trace:
    """Return a copy of ``trace`` enriched with the executed source file.

    The source text is read from ``source_path`` and always embedded when the
    file is readable. Reading failures (missing/unreadable file) propagate as
    :class:`OSError` because the caller explicitly requested embedding via
    ``--source``; the CLI turns that into a hard error.

    Locating the defining function is best-effort: a syntax error, non-Python
    source, or an ambiguous/absent function match emits a warning and omits
    ``definitionLineRange`` while still embedding ``sourceText``.
    """
    warn = warn or _noop
    source_text = source_path.read_text(encoding="utf-8")

    application = trace.application or Application(function_name="")
    if application.source_file is not None and application.source_file != source_path.name:
        warn(
            f"funcviz: --source basename {source_path.name!r} differs from "
            f"log-reported sourceFile {application.source_file!r}; using --source."
        )
    source_file = source_path.name

    line_range = _definition_line_range(
        source_text,
        source_path,
        application.function_name,
        warn=warn,
    )

    enriched = replace(
        application,
        source_file=source_file,
        source_text=source_text,
        definition_line_range=line_range,
        highlight_confidence="inferred" if line_range is not None else None,
    )
    return replace(
        trace,
        application=enriched,
        failures=_failures_with_source_lines(trace, source_file, source_text),
    )


def _failures_with_source_lines(
    trace: Trace, source_file: str, source_text: str
) -> tuple[Failure, ...]:
    line_count = len(source_text.removesuffix("\n").split("\n")) if source_text else 0
    raw_by_event = {e.id: e.raw for e in trace.events}
    augmented = []
    for failure in trace.failures:
        raw = raw_by_event.get(failure.event or "") or ""
        line = match_traceback_source_line(raw, source_file) if raw else None
        if line is not None and line <= line_count:
            augmented.append(replace(failure, source_line=line, source_confidence="inferred"))
        else:
            augmented.append(failure)
    return tuple(augmented)


def _definition_line_range(
    source_text: str,
    source_path: Path,
    function_name: str,
    *,
    warn: Warn,
) -> tuple[int, int] | None:
    if source_path.suffix != ".py":
        warn(
            f"funcviz: {source_path.name} is not a Python source file; "
            "omitting definitionLineRange."
        )
        return None
    if not function_name:
        warn("funcviz: no application function name available; omitting definitionLineRange.")
        return None

    try:
        tree = ast.parse(source_text)
    except SyntaxError as exc:
        warn(f"funcviz: could not parse {source_path.name} ({exc}); omitting definitionLineRange.")
        return None

    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name
    ]
    if len(matches) != 1:
        detail = "no match" if not matches else f"{len(matches)} matches"
        warn(
            f"funcviz: function {function_name!r} has {detail} in {source_path.name}; "
            "omitting definitionLineRange."
        )
        return None

    node = matches[0]
    start = node.decorator_list[0].lineno if node.decorator_list else node.lineno
    end = node.end_lineno
    if end is None or start < 1 or start > end:
        warn(
            f"funcviz: invalid line range for {function_name!r} in {source_path.name}; "
            "omitting definitionLineRange."
        )
        return None
    return (start, end)
