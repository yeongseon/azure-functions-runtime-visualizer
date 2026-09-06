"""Frozen data models backing the v0.1 trace schema (schemas/trace-0.1.json).

These are the parser's output types and the single serialization boundary:
``Trace.to_dict()`` maps 1:1 onto the frozen schema's shape. A handful of
cheap structural invariants (non-empty events, ``failed-here`` requires a
``failureEvent``) are enforced in ``__post_init__``; richer semantic validation
(id cross-references, ordering, duration provenance) is the parser's job, so a
well-formed ``Trace`` serializes to schema-valid JSON but the models do not
re-implement the full JSON Schema.
``LogRecord`` is the parser's *input* type and is deliberately not narrowed to
``str`` (PRD FR-2.1) so future adapters can carry structured fields.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

SCHEMA_VERSION = "0.1"


class Lane(str, Enum):
    CLIENT = "client"
    HOST = "host"
    PYTHON_WORKER = "python-worker"
    APPLICATION = "application"


class Confidence(str, Enum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    INSTRUMENTED = "instrumented"


class Outcome(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"


class LaneState(str, Enum):
    REACHED = "reached"
    NOT_REACHED = "not-reached"
    FAILED_HERE = "failed-here"
    UNKNOWN = "unknown"


class IntervalSource(str, Enum):
    LOG_DELTA = "log-delta"
    HOST_REPORTED = "host-reported"
    HTTP_REPORTED = "http-reported"
    INFERRED = "inferred"
    PROVIDER_REPORTED = "provider-reported"


@dataclass(frozen=True)
class LogRecord:
    message: str
    timestamp: datetime | None = None
    fields: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TraceInput:
    source: str
    adapter: str | None = None
    adapter_version: str | None = None
    extra: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {"source": self.source}
        if self.adapter is not None:
            out["adapter"] = self.adapter
        if self.adapter_version is not None:
            out["adapterVersion"] = self.adapter_version
        out.update({k: v for k, v in self.extra.items() if k not in out})
        return out


@dataclass(frozen=True)
class Runtime:
    environment: str
    language: str
    trigger: str
    core_tools_version: str | None = None
    host_version: str | None = None

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "environment": self.environment,
            "language": self.language,
            "trigger": self.trigger,
        }
        if self.core_tools_version is not None:
            out["coreToolsVersion"] = self.core_tools_version
        if self.host_version is not None:
            out["hostVersion"] = self.host_version
        return out


@dataclass(frozen=True)
class Application:
    function_name: str
    source_file: str | None = None
    source_text: str | None = None
    definition_line_range: tuple[int, int] | None = None
    highlight_confidence: str | None = None

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {"functionName": self.function_name}
        if self.source_file is not None:
            out["sourceFile"] = self.source_file
        if self.source_text is not None:
            out["sourceText"] = self.source_text
        if self.definition_line_range is not None:
            out["definitionLineRange"] = list(self.definition_line_range)
        if self.highlight_confidence is not None:
            out["highlightConfidence"] = self.highlight_confidence
        return out


@dataclass(frozen=True)
class LaneStatus:
    status: LaneState
    confidence: Confidence
    reason: str | None = None
    failure_event: str | None = None

    def __post_init__(self) -> None:
        if self.status is LaneState.FAILED_HERE and self.failure_event is None:
            raise ValueError("LaneStatus with status 'failed-here' requires a failure_event")

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {"status": self.status.value, "confidence": self.confidence.value}
        if self.reason is not None:
            out["reason"] = self.reason
        if self.failure_event is not None:
            out["failureEvent"] = self.failure_event
        return out


@dataclass(frozen=True)
class Lanes:
    client: LaneStatus
    host: LaneStatus
    python_worker: LaneStatus
    application: LaneStatus

    def to_dict(self) -> dict[str, object]:
        return {
            "client": self.client.to_dict(),
            "host": self.host.to_dict(),
            "python-worker": self.python_worker.to_dict(),
            "application": self.application.to_dict(),
        }


@dataclass(frozen=True)
class Event:
    id: str
    sequence: int
    lane: Lane
    event: str
    confidence: Confidence
    raw: str | None
    timestamp: str | None = None
    elapsed_ms: float | None = None
    http_request_id: str | None = None
    worker_request_id: str | None = None
    invocation_id: str | None = None
    correlation: Mapping[str, str] = field(default_factory=dict)
    attributes: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {"id": self.id, "sequence": self.sequence}
        if self.timestamp is not None:
            out["timestamp"] = self.timestamp
        if self.elapsed_ms is not None:
            out["elapsedMs"] = self.elapsed_ms
        out["lane"] = self.lane.value
        out["event"] = self.event
        if self.http_request_id is not None:
            out["httpRequestId"] = self.http_request_id
        if self.worker_request_id is not None:
            out["workerRequestId"] = self.worker_request_id
        if self.invocation_id is not None:
            out["invocationId"] = self.invocation_id
        if self.correlation:
            out["correlation"] = dict(self.correlation)
        out["confidence"] = self.confidence.value
        if self.attributes:
            out["attributes"] = dict(self.attributes)
        out["raw"] = self.raw
        return out


@dataclass(frozen=True)
class Interval:
    id: str
    label: str
    lane: Lane
    kind: str
    start_event: str
    end_event: str
    duration_ms: float
    source: IntervalSource
    confidence: Confidence
    attributes: Mapping[str, object] = field(default_factory=dict)
    raw: str | None = None

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "id": self.id,
            "label": self.label,
            "lane": self.lane.value,
            "kind": self.kind,
            "startEvent": self.start_event,
            "endEvent": self.end_event,
            "durationMs": self.duration_ms,
            "source": self.source.value,
            "confidence": self.confidence.value,
        }
        if self.attributes:
            out["attributes"] = dict(self.attributes)
        if self.raw is not None:
            out["raw"] = self.raw
        return out


@dataclass(frozen=True)
class Failure:
    event: str | None = None
    kind: str | None = None
    message: str | None = None
    source_line: int | None = None
    source_confidence: str | None = None
    extra: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {}
        if self.event is not None:
            out["event"] = self.event
        if self.kind is not None:
            out["kind"] = self.kind
        if self.message is not None:
            out["message"] = self.message
        if self.source_line is not None:
            out["sourceLine"] = self.source_line
        if self.source_confidence is not None:
            out["sourceConfidence"] = self.source_confidence
        out.update({k: v for k, v in self.extra.items() if k not in out})
        return out


@dataclass(frozen=True)
class Trace:
    trace_id: str
    outcome: Outcome
    input: TraceInput
    runtime: Runtime
    lanes: Lanes
    events: Sequence[Event]
    intervals: Sequence[Interval] = ()
    application: Application | None = None
    failures: Sequence[Failure] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.events:
            raise ValueError("Trace requires at least one event")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"Trace.schema_version must be {SCHEMA_VERSION!r}")

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "schemaVersion": self.schema_version,
            "traceId": self.trace_id,
            "outcome": self.outcome.value,
            "input": self.input.to_dict(),
            "runtime": self.runtime.to_dict(),
        }
        if self.application is not None:
            out["application"] = self.application.to_dict()
        out["lanes"] = self.lanes.to_dict()
        out["events"] = [e.to_dict() for e in self.events]
        out["intervals"] = [i.to_dict() for i in self.intervals]
        if self.failures:
            out["failures"] = [f.to_dict() for f in self.failures]
        if self.metadata:
            out["metadata"] = dict(self.metadata)
        return out
