"""The only module in the parser that touches ``re`` (PRD R1 mitigation).

Every log-shape assumption lives here as a named pattern with a typed accessor.
Downstream stages consume the returned match dictionaries and never see raw
regex groups, so a Core Tools log-format change is a one-file edit.
"""

from __future__ import annotations

import re

_TIMESTAMP = re.compile(r"^\[(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z)\]\s?(?P<rest>.*)$")
_WORKER_RUNTIME = re.compile(r"Resolving worker runtime to '(?P<lang>[^']+)'")
_CORE_TOOLS_VERSION = re.compile(r"Core Tools Version:\s*(?P<version>\S+)")
_RUNTIME_VERSION = re.compile(r"Function Runtime Version:\s*(?P<version>\S+)")
_FUNCTION_PATH = re.compile(r"function_path:\s*(?P<path>\S+)")

_INVOCATION_STARTED = re.compile(
    r"Executing 'Functions\.(?P<name>[^']+)'.*\bId=(?P<invocation>[0-9a-fA-F-]{36})"
)
_INVOCATION_COMPLETED = re.compile(
    r"Executed 'Functions\.(?P<name>[^']+)' \((?P<result>Succeeded|Failed), "
    r"Id=(?P<invocation>[0-9a-fA-F-]{36}), Duration=(?P<duration>\d+)ms\)"
)
_WORKER_INVOCATION = re.compile(
    r"Received FunctionInvocationRequest, request ID: (?P<worker>[0-9a-fA-F-]{36}),"
    r".*invocation ID: (?P<invocation>[0-9a-fA-F-]{36})"
)
_HTTP_REQUEST_ID = re.compile(r'"requestId":\s*"(?P<http>[0-9a-fA-F-]{36})"')
_HTTP_STATUS = re.compile(r'"status":\s*"(?P<status>\d+)"')
_HTTP_DURATION = re.compile(r'"duration":\s*"(?P<duration>\d+)"')

_HTTP_REQUEST_START = "Executing HTTP request:"
_HTTP_RESPONSE_START = "Executed HTTP request:"


def split_timestamp(line: str) -> tuple[str | None, str]:
    m = _TIMESTAMP.match(line)
    if m is None:
        return None, line
    return m.group("ts"), m.group("rest")


def is_http_request_start(content: str) -> bool:
    return content.startswith(_HTTP_REQUEST_START)


def is_http_response_start(content: str) -> bool:
    return content.startswith(_HTTP_RESPONSE_START)


def match_invocation_started(content: str) -> dict[str, str] | None:
    m = _INVOCATION_STARTED.search(content)
    return m.groupdict() if m else None


def match_invocation_completed(content: str) -> dict[str, str] | None:
    m = _INVOCATION_COMPLETED.search(content)
    return m.groupdict() if m else None


def match_worker_invocation(content: str) -> dict[str, str] | None:
    m = _WORKER_INVOCATION.search(content)
    return m.groupdict() if m else None


def find_http_request_id(content: str) -> str | None:
    m = _HTTP_REQUEST_ID.search(content)
    return m.group("http") if m else None


def find_http_status(content: str) -> str | None:
    m = _HTTP_STATUS.search(content)
    return m.group("status") if m else None


def find_http_duration(content: str) -> str | None:
    m = _HTTP_DURATION.search(content)
    return m.group("duration") if m else None


def find_worker_runtime(content: str) -> str | None:
    m = _WORKER_RUNTIME.search(content)
    return m.group("lang") if m else None


def find_core_tools_version(content: str) -> str | None:
    m = _CORE_TOOLS_VERSION.search(content)
    return m.group("version") if m else None


def find_runtime_version(content: str) -> str | None:
    m = _RUNTIME_VERSION.search(content)
    return m.group("version") if m else None


def find_function_path(content: str) -> str | None:
    m = _FUNCTION_PATH.search(content)
    return m.group("path") if m else None
