"""funcviz command-line interface (PRD FR-1, FR-3).

Three subcommands, all pure log *readers* — funcviz never starts, wraps, or
supervises the Azure Functions host:

* ``parse``  — turn a log file (or stdin) into schema-0.1 trace JSON.
* ``view``   — open a trace in the self-contained static viewer.
* ``record`` — read stdin until EOF/Ctrl-C and write the resulting trace.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import json
import sys
import tempfile
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import TextIO
from urllib.request import pathname2url

from funcviz.models import LogRecord
from funcviz.parser import from_log_text, mask_records, parse_trace
from funcviz.source import enrich_trace_from_source

Opener = Callable[[str], object]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="funcviz",
        description="Azure Functions runtime log visualizer.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    parse_cmd = subparsers.add_parser(
        "parse",
        help="Parse Azure Functions runtime logs into funcviz trace JSON.",
    )
    parse_cmd.add_argument("input", help="Log file path, or '-' to read from stdin.")
    parse_cmd.add_argument(
        "-o",
        "--output",
        default="-",
        help="Output trace JSON path, or '-' for stdout (default: stdout).",
    )
    parse_cmd.add_argument("--trace-id", help="Override the generated traceId.")
    parse_cmd.add_argument(
        "--source",
        help="Executed application source file to embed for the viewer's source panel.",
    )
    parse_cmd.add_argument(
        "--no-mask",
        action="store_true",
        help="Do not redact secrets; emit raw log text verbatim (masking is on by default).",
    )
    parse_cmd.set_defaults(handler=cmd_parse)

    view_cmd = subparsers.add_parser(
        "view",
        help="Open a trace JSON file in the static funcviz viewer.",
    )
    view_cmd.add_argument("trace", help="Trace JSON file to view.")
    view_cmd.add_argument(
        "--port",
        type=int,
        default=0,
        help="Local port for the viewer server (default: ephemeral).",
    )
    view_cmd.add_argument(
        "--no-browser",
        action="store_true",
        help="Start the server but do not open a browser; print the URL.",
    )
    view_cmd.add_argument(
        "--html-out",
        help="Write a standalone HTML viewer to this path and exit (no server).",
    )
    view_cmd.add_argument(
        "--direct",
        action="store_true",
        help="Open a standalone file:// HTML viewer instead of starting a server.",
    )
    view_cmd.set_defaults(handler=cmd_view)

    record_cmd = subparsers.add_parser(
        "record",
        help="Read logs from stdin until termination and write trace JSON.",
    )
    record_cmd.add_argument(
        "-o",
        "--output",
        required=True,
        help="Output trace JSON path, or '-' for stdout.",
    )
    record_cmd.add_argument("--trace-id", help="Override the generated traceId.")
    record_cmd.add_argument(
        "--no-mask",
        action="store_true",
        help="Do not redact secrets; emit raw log text verbatim (masking is on by default).",
    )
    record_cmd.set_defaults(handler=cmd_record)

    return parser


def main(
    argv: list[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    opener: Opener | None = None,
) -> int:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    stderr = stderr if stderr is not None else sys.stderr
    if opener is None:
        import webbrowser

        opener = webbrowser.open

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return args.handler(args, stdin=stdin, stdout=stdout, stderr=stderr, opener=opener)
    except (OSError, ValueError) as exc:
        print(f"funcviz: {exc}", file=stderr)
        return 1


def cmd_parse(args, *, stdin: TextIO, stdout: TextIO, stderr: TextIO, opener: Opener) -> int:
    text = _read_text_arg(args.input, stdin)
    trace_id = args.trace_id or _default_trace_id(args.input, text)
    trace = parse_trace(_records(text, no_mask=args.no_mask), trace_id=trace_id)
    if args.source:
        trace = enrich_trace_from_source(
            trace,
            Path(args.source),
            warn=lambda message: print(message, file=stderr),
        )
    _write_json(trace.to_dict(), args.output, stdout)
    return 0


def cmd_view(args, *, stdin: TextIO, stdout: TextIO, stderr: TextIO, opener: Opener) -> int:
    trace_obj = _read_json_file(args.trace)
    html_text = _inject_default_trace(_load_viewer_template(), trace_obj)

    if args.html_out:
        out_path = Path(args.html_out)
        out_path.write_text(html_text, encoding="utf-8")
        print(str(out_path), file=stdout)
        if args.direct:
            opener(_file_url(out_path))
        return 0

    if args.direct:
        path = _write_persistent_temp_html(html_text)
        print(str(path), file=stdout)
        opener(_file_url(path))
        return 0

    with tempfile.TemporaryDirectory(prefix="funcviz-view-") as temp_dir:
        temp_path = Path(temp_dir)
        (temp_path / "index.html").write_text(html_text, encoding="utf-8")
        return _serve_directory(
            temp_path,
            port=args.port,
            stdout=stdout,
            stderr=stderr,
            opener=opener,
            no_browser=args.no_browser,
        )


def cmd_record(args, *, stdin: TextIO, stdout: TextIO, stderr: TextIO, opener: Opener) -> int:
    chunks: list[str] = []
    try:
        while True:
            chunk = stdin.read(8192)
            if not chunk:
                break
            chunks.append(chunk)
    except KeyboardInterrupt:
        print("funcviz: interrupted; writing partial trace.", file=stderr)

    text = "".join(chunks)
    trace_id = args.trace_id or _hash_trace_id("record", text)
    trace = parse_trace(_records(text, no_mask=args.no_mask), trace_id=trace_id)
    _write_json(trace.to_dict(), args.output, stdout)
    return 0


def _records(text: str, *, no_mask: bool) -> list[LogRecord]:
    records = from_log_text(text)
    return records if no_mask else mask_records(records)


def _read_text_arg(input_arg: str, stdin: TextIO) -> str:
    if input_arg == "-":
        return stdin.read()
    return Path(input_arg).read_text(encoding="utf-8")


def _write_text_arg(output_arg: str, text: str, stdout: TextIO) -> None:
    if output_arg == "-":
        stdout.write(text)
        stdout.flush()
    else:
        Path(output_arg).write_text(text, encoding="utf-8")


def _write_json(obj: object, output_arg: str, stdout: TextIO) -> None:
    text = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    _write_text_arg(output_arg, text, stdout)


def _read_json_file(path_arg: str) -> object:
    with Path(path_arg).open("r", encoding="utf-8") as handle:
        try:
            return json.load(handle)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path_arg}: not valid JSON ({exc})") from exc


def _default_trace_id(input_arg: str, text: str) -> str:
    if input_arg != "-":
        stem = Path(input_arg).stem
        if stem:
            return stem
    return _hash_trace_id("stdin", text)


def _hash_trace_id(prefix: str, text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


_DEFAULT_TRACE_ID = "funcviz-default-trace"


def _json_for_script_tag(obj: object) -> str:
    """Serialize JSON safe to embed inside an HTML ``<script>`` element."""
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return (
        text.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _find_default_trace_script(index_html: str) -> tuple[int, int]:
    matches: list[tuple[int, int]] = []
    search = 0
    while True:
        open_start = index_html.find("<script", search)
        if open_start == -1:
            break
        open_end = index_html.find(">", open_start)
        if open_end == -1:
            break
        tag = index_html[open_start : open_end + 1]
        if _DEFAULT_TRACE_ID in tag and "application/json" in tag:
            close_start = index_html.find("</script>", open_end)
            if close_start != -1:
                matches.append((open_end + 1, close_start))
        search = open_end + 1
    if len(matches) != 1:
        raise ValueError(
            "viewer template must contain exactly one funcviz-default-trace "
            f"script tag (found {len(matches)})"
        )
    return matches[0]


def _inject_default_trace(index_html: str, trace_obj: object) -> str:
    safe_json = _json_for_script_tag(trace_obj)
    body_start, body_end = _find_default_trace_script(index_html)
    return index_html[:body_start] + "\n" + safe_json + "\n" + index_html[body_end:]


def _load_viewer_template() -> str:
    return resources.files("funcviz").joinpath("viewer", "index.html").read_text(encoding="utf-8")


def _file_url(path: Path) -> str:
    return "file://" + pathname2url(str(path.resolve()))


def _write_persistent_temp_html(html_text: str) -> Path:
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".html",
        prefix="funcviz-",
        delete=False,
    )
    with handle:
        handle.write(html_text)
    return Path(handle.name)


def _serve_directory(
    directory: Path,
    *,
    port: int,
    stdout: TextIO,
    stderr: TextIO,
    opener: Opener,
    no_browser: bool,
) -> int:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as server:
        actual_port = server.server_address[1]
        url = f"http://127.0.0.1:{actual_port}/index.html"
        print(f"funcviz viewer: {url}", file=stdout)
        print("Press Ctrl-C to stop.", file=stderr)
        if not no_browser:
            opener(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("", file=stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
