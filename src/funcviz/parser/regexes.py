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
_HTTP_DURATION = re.compile(r'"duration":\s*"(?P<duration>\d+)"')

_HTTP_REQUEST_START = "Executing HTTP request:"
_HTTP_RESPONSE_START = "Executed HTTP request:"

_HOST_BUILD_STARTED = "Building host:"
_WORKER_INDEXING_ENABLED = "Worker indexing is enabled"
_PYTHON_WORKER_STARTED = "Starting Azure Functions Python Worker"
_WORKER_FAILED_TO_INDEX = "Worker failed to index functions"
_WORKER_METADATA_REQUEST = re.compile(
    r"Received WorkerMetadataRequest, request ID:?\s*(?P<worker>[0-9a-fA-F-]{36})"
)
_MODULE_NOT_FOUND = re.compile(r"ModuleNotFoundError: No module named '(?P<module>[^']+)'")


def split_timestamp(line: str) -> tuple[str | None, str]:
    m = _TIMESTAMP.match(line)
    if m is None:
        return None, line
    return m.group("ts"), m.group("rest")


def is_http_request_start(content: str) -> bool:
    return content.startswith(_HTTP_REQUEST_START)


def is_http_response_start(content: str) -> bool:
    return content.startswith(_HTTP_RESPONSE_START)


def is_host_build_started(content: str) -> bool:
    return content.startswith(_HOST_BUILD_STARTED)


def is_worker_indexing_started(content: str) -> bool:
    return content.startswith(_WORKER_INDEXING_ENABLED)


def is_python_worker_started(content: str) -> bool:
    return _PYTHON_WORKER_STARTED in content


def is_worker_failed_to_index(content: str) -> bool:
    return content.startswith(_WORKER_FAILED_TO_INDEX)


def match_worker_metadata_request(content: str) -> dict[str, str] | None:
    m = _WORKER_METADATA_REQUEST.search(content)
    return m.groupdict() if m else None


def find_module_not_found(content: str) -> str | None:
    m = _MODULE_NOT_FOUND.search(content)
    return m.group("module") if m else None


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


# ---- secret redaction (issue #11, PRD §16) -------------------------------
# Value-capture classes stop at the delimiters that bound a secret in a log
# line or a folded multiline JSON block, so a match never spills across quotes,
# separators, or line breaks into a neighbouring field.
_HEADER_VALUE = r"[^\s\"',}\r\n]+"
_QUERY_VALUE = r"[^\s\"'&,;}#\r\n]+"
_CONN_VALUE = r"[^;\s\"',}\r\n]+"

# Optional quote around a header key or the start of its value, so the same
# rule covers both flat log lines (Authorization: Bearer x) and folded JSON
# blocks ("Authorization": "Bearer x"). The quote stays in the kept prefix.
_Q = r"[\"']?"

# A generic (non-Bearer/Basic) Authorization value can carry an arbitrary
# scheme with embedded spaces (ApiKey secret, Digest realm="x", ...), so it is
# redacted whole rather than only its first whitespace-delimited token, which
# would leak the credential tail. A JSON-quoted value stops at its closing
# quote; an unquoted value runs to end-of-line (which may contain its own
# embedded quotes, e.g. Digest). Both require a non-whitespace first character
# so the separator's trailing \s* cannot backtrack and expose the negative
# lookahead to a leading space -- that backtrack would otherwise let the rule
# re-swallow an already Bearer/Basic-masked value and drop the ': "' separator.
_AUTH_QUOTED_VALUE = r"[^\s\"'\r\n][^\"'\r\n]*"
_AUTH_LINE_VALUE = r"[^\s\r\n][^\r\n]*"

# (pattern, replacement) pairs applied in order. Bearer/Basic run before the
# generic Authorization rule -- whose negative lookahead then skips those
# schemes and any existing marker -- so each secret gets one typed marker and
# re-masking is a no-op (a value class re-captures a whole marker and rewrites
# it to itself). Every rule keeps its key visible and redacts only the value,
# and none of the classes overlap the invocation IDs, durations, status codes,
# ports, or GUIDs the extractor depends on.
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(" + _Q + r"Authorization" + _Q + r"\s*:\s*" + _Q + r"Bearer\s+)" + _HEADER_VALUE,
            re.IGNORECASE,
        ),
        r"\1[REDACTED:bearer-token]",
    ),
    (
        re.compile(
            r"(" + _Q + r"Authorization" + _Q + r"\s*:\s*" + _Q + r"Basic\s+)" + _HEADER_VALUE,
            re.IGNORECASE,
        ),
        r"\1[REDACTED:basic-auth]",
    ),
    (
        re.compile(
            r"(" + _Q + r"Authorization" + _Q + r"\s*:\s*[\"'])"
            r"(?!Bearer\b|Basic\b|\[REDACTED)" + _AUTH_QUOTED_VALUE,
            re.IGNORECASE,
        ),
        r"\1[REDACTED:authorization]",
    ),
    (
        re.compile(
            r"(" + _Q + r"Authorization" + _Q + r"\s*:\s*)"
            r"(?![\"']|Bearer\b|Basic\b|\[REDACTED)" + _AUTH_LINE_VALUE,
            re.IGNORECASE,
        ),
        r"\1[REDACTED:authorization]",
    ),
    (
        re.compile(r"([?&](?:code|x-functions-key)=)" + _QUERY_VALUE, re.IGNORECASE),
        r"\1[REDACTED:function-key]",
    ),
    (
        re.compile(
            r"(" + _Q + r"x-functions-key" + _Q + r"\s*:\s*" + _Q + r")" + _HEADER_VALUE,
            re.IGNORECASE,
        ),
        r"\1[REDACTED:function-key]",
    ),
    # MasterKey=<value> is a function/master key in the same class as the
    # header/query function-key rules above. The lookbehind stops it firing on
    # a longer word ending in "MasterKey", and the negative lookahead makes a
    # second pass a no-op (the marker is not re-captured as a value).
    (
        re.compile(
            r"((?<![A-Za-z])MasterKey=" + _Q + r")(?!\[REDACTED:function-key\])" + _CONN_VALUE,
            re.IGNORECASE,
        ),
        r"\1[REDACTED:function-key]",
    ),
    (re.compile(r"(AccountKey=)" + _CONN_VALUE, re.IGNORECASE), r"\1[REDACTED:storage-key]"),
    (
        re.compile(r"(SharedAccessKey=)(?!Name=)" + _CONN_VALUE, re.IGNORECASE),
        r"\1[REDACTED:shared-access-key]",
    ),
    (re.compile(r"([?&;]sig=)" + _QUERY_VALUE, re.IGNORECASE), r"\1[REDACTED:sas]"),
    (re.compile(r"(SharedAccessSignature=)" + _CONN_VALUE, re.IGNORECASE), r"\1[REDACTED:sas]"),
    # Generic connection-string secrets (semicolon-delimited). AccessKey= is
    # guarded so it never re-fires on the tail of SharedAccessKey=.
    (re.compile(r"((?:Password|Pwd)=)" + _CONN_VALUE, re.IGNORECASE), r"\1[REDACTED:password]"),
    # A connection URI carries its credential as scheme://user:pass@host. The
    # whole user:pass is masked (a username can leak a service account, tenant,
    # or topology) while scheme://, @host, port, and path stay verbatim -- the
    # match ends at the @. The user/pass classes exclude URL structure chars so
    # a match never crosses into host/port/query, and the negative lookahead on
    # the marker keeps a second pass a no-op. scheme://host with no user:pass@
    # (e.g. sb://ns/, http://localhost:7071/api) never matches.
    (
        re.compile(
            r"([A-Za-z][A-Za-z0-9+.-]*://)"
            r"(?!\[REDACTED:connection-credential\]@)"
            r"[^\s\"',;{}\[\]/?#@:]+:[^@\s\"',;{}\[\]/?#]+@",
            re.IGNORECASE,
        ),
        r"\1[REDACTED:connection-credential]@",
    ),
    (re.compile(r"(ClientSecret=)" + _CONN_VALUE, re.IGNORECASE), r"\1[REDACTED:client-secret]"),
    (
        re.compile(r"(?<![A-Za-z])(AccessKey=)" + _CONN_VALUE, re.IGNORECASE),
        r"\1[REDACTED:access-key]",
    ),
)


def redact_secrets(content: str) -> str:
    for pattern, replacement in _REDACTIONS:
        content = pattern.sub(replacement, content)
    return content
