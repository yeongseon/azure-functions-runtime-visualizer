#!/usr/bin/env python3
"""Canonical regenerator for the committed golden traces (AC6/AC10 durability).

Each golden trace under ``traces/`` is produced by exactly one ``funcviz parse``
invocation. Encoding those invocations here — rather than in a README a human
must remember to follow — means a future trace change cannot silently drop the
embedded source or use the wrong ``--trace-id``.

Honesty rule (PRD §7.2): only traces whose ``application`` lane actually reaches
user-code embed ``--source``. ``worker-unobserved`` (application=unknown) and
``worker-fail`` (no application block) must *not* embed source.

Regeneration drives the real :func:`funcviz.cli.main` ``parse`` code path with
``-o -`` so the bytes are identical to what ``funcviz parse`` writes; the script
never reimplements the parse/enrich/serialize pipeline.

Usage::

    python scripts/regen_traces.py           # rewrite traces/*.json in place
    python scripts/regen_traces.py --check    # fail if any trace is stale
"""

from __future__ import annotations

import argparse
import io
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
# Allows running from a source checkout without `pip install -e .` (CI installs
# the package, so the insert is a no-op there — sys.path already contains it).
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from funcviz import cli  # noqa: E402  (path set up above)

SAMPLES = ROOT / "samples"
TRACES = ROOT / "traces"
SOURCE = ROOT / "examples" / "python-http-trigger" / "function_app.py"


@dataclass(frozen=True)
class Golden:
    """One committed golden trace and how to regenerate it."""

    stem: str
    trace_id: str
    source: bool  # embed --source (only when application reaches user code)

    @property
    def log_path(self) -> Path:
        return SAMPLES / f"{self.stem}.log"

    @property
    def trace_path(self) -> Path:
        return TRACES / f"{self.stem}.json"


GOLDENS: tuple[Golden, ...] = (
    Golden("success", "success-001", source=True),
    Golden("invocation-fail", "invocation-fail-001", source=True),
    Golden("worker-unobserved", "worker-unobserved-001", source=False),
    Golden("worker-fail", "worker-fail-001", source=False),
)


def render(golden: Golden) -> str:
    """Return the canonical JSON text for ``golden`` via the real CLI path."""
    argv = ["parse", str(golden.log_path), "-o", "-", "--trace-id", golden.trace_id]
    if golden.source:
        argv += ["--source", str(SOURCE)]
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = cli.main(
        argv,
        stdin=io.StringIO(""),
        stdout=stdout,
        stderr=stderr,
        opener=lambda _url: None,
    )
    if code != 0:
        raise RuntimeError(f"funcviz parse failed for {golden.stem}: {stderr.getvalue()}")
    return stdout.getvalue()


def _write(golden: Golden) -> None:
    golden.trace_path.write_text(render(golden), encoding="utf-8")


def _check(golden: Golden) -> bool:
    """Return True when the committed trace matches a fresh render."""
    expected = render(golden)
    try:
        actual = golden.trace_path.read_text(encoding="utf-8")
    except OSError:
        return False
    return actual == expected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate the committed golden traces via the real CLI path."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify committed traces are up to date instead of rewriting them",
    )
    args = parser.parse_args(argv)

    if args.check:
        stale = [g.stem for g in GOLDENS if not _check(g)]
        if stale:
            print("stale golden traces (run `make traces`): " + ", ".join(stale))
            return 1
        print(f"all {len(GOLDENS)} golden traces up to date")
        return 0

    for golden in GOLDENS:
        _write(golden)
    print(f"regenerated {len(GOLDENS)} golden traces")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
