# Azure Functions Runtime Visualizer — Product Requirements Document

**Status:** Draft v2 (post-review)
**Repository name:** `azure-functions-runtime-visualizer` *(decided — see §13)*
**CLI name:** `funcviz`
**v0.1 scope:** Local Azure Functions + Python + HTTP trigger, log-file input, replay-only
**Budget:** 2–3 weekends. This constraint is a requirement, not an estimate.

---

## 1. Product Summary

`funcviz` turns Azure Functions verbose runtime logs into an interactive execution timeline.

The user runs a local Function App with verbose logging, pipes or saves the output, and gets a
replayable visualization that separates **Client**, **Functions Host**, and **Python Worker**
activity, alongside the application source file that was executed.

The tool does not launch, wrap, or manage the Functions host. It reads logs. That single
constraint is what makes the project shippable in a weekend-scale budget and portable to
production log sources later.

---

## 2. What Changed From v1 of This PRD, and Why

| v1 | v2 | Reason |
|---|---|---|
| `collector/` wraps `func start` via subprocess | Read from stdin or a file | Wrapping owns ANSI stripping, buffering, Ctrl+C signal forwarding, and cross-platform process teardown. That is the entire budget, spent on plumbing no user values. |
| Success-path replay only in v0.1 | One success trace **and** one failure trace | The success path is the case nobody needs help with. The failure path is where the tool earns its existence. Shipping only the happy path would mean discovering the schema is wrong later. |
| Storage topology, hosting-plan matrix, Azure Connected Mode, Sync Triggers specified in the PRD | Moved to `IDEAS.md`, unspecified | None of it is validated. Mixing speculation into a spec makes it unclear which parts are commitments. |
| Log parsing assumed | Log parsing **confirmed**; OpenTelemetry deferred | Functions supports `"telemetryMode": "OpenTelemetry"` in `host.json`, which exports from both host and worker processes. That is structurally better data, but it requires the user to run an OTLP receiver — which breaks the "one command, no setup" property that makes this installable. Revisit in v0.2. |
| Host↔Worker boundary assumed visible | Boundary visibility **confirmed** observable under elevated capture logging | Phase 0 proved the same `invocationId` appears on both the host and worker invocation lines. See §9 and §10. |

---

## 3. Problem Statement

Azure Functions runtime logs report *what* happened but not *where*. A reader cannot tell from
log text alone which component was active, when control crossed from the Host into the language
worker, when user code actually began, or — for a failure — how far the lifecycle got before it
stopped.

For support engineers, SME presentations, and onboarding, an ordered timeline with explicit
component ownership communicates this far faster than a log excerpt.

---

## 4. v0.1 Scope

**In scope**

- Azure Functions Core Tools, local execution
- Python language worker, HTTP trigger
- A single invocation per trace
- Replay only (no live streaming view)
- Two shipped sample traces: one successful invocation, one runtime failure
- Python package on PyPI, `funcviz` CLI, local static viewer

**Out of scope for v0.1** — explicitly, and not to be reopened during implementation:

Azure connectivity of any kind · Application Insights · ARM calls · Sync Triggers · storage or
deployment topology · hosting-plan awareness · queue/timer/Service Bus triggers · Durable
Functions · Node/Java/.NET workers · multi-instance or scale-out · gRPC interception · any
modification to the Host or the Python worker · exact line-by-line application tracing ·
concurrent invocation correlation

---

## 5. Input Model and CLI

The user is responsible for producing the log. The tool is responsible for everything after that.

```
# Capture
func start --verbose > run.log
```

**A plain `func start --verbose` is not sufficient to populate the Python Worker lane.** Phase 0
confirmed (see `docs/event-coverage.md`) that the worker gRPC/channel lines and the worker-side
invocation receipt only appear when worker and gRPC log categories are elevated in `host.json` and
Python worker debug logging is enabled. The capture procedure the tool documents and ships as its
example is therefore:

```jsonc
// host.json — elevate the categories the worker lane depends on
{
  "logging": {
    "logLevel": {
      "Microsoft.Azure.WebJobs.Script.Grpc": "Trace",
      "Worker": "Trace",
      "Host.Function.Console": "Trace"
    }
  }
}
```

```
# local.settings.json (or the environment) must also set:
#   PYTHON_ENABLE_DEBUG_LOGGING = 1
func start --verbose > run.log
```

Without both, the Host lane and the HTTP-derived Client lane still populate, but the Worker lane is
empty — which is a legitimate `not-reached`/`unknown` lane status (see §6), not a parser bug. The
shipped `examples/python-http-trigger/host.json` already carries the elevated configuration so the
sample logs are reproducible.

```
# Parse
funcviz parse run.log -o trace.json

# View
funcviz view trace.json
```

Live-feeling demo mode, same code path:

```
func start --verbose | tee run.log | funcviz record -o trace.json
```

**FR-1 — Input**
`funcviz parse` accepts a file path or `-` for stdin. `funcviz record` reads stdin continuously
and writes a trace on termination. No process management, no PTY, no subprocess supervision.

**FR-2 — Parser purity and input shape**
The parser is a pure function: `Iterable[LogRecord] -> Trace`. It must not perform file I/O, know
about the CLI, or know where the records came from.

`LogRecord` is deliberately not a plain string:

```python
@dataclass(frozen=True)
class LogRecord:
    message: str
    timestamp: datetime | None = None
    fields: Mapping[str, str] = field(default_factory=dict)
```

Local Core Tools lines are wrapped as `LogRecord(message=line)` and nothing else is populated in
v0.1. The cost today is one dataclass; the reason is §5.1.

**FR-2.1 — Do not narrow at the boundary**
Any current or future input adapter must preserve structured fields it receives rather than
flattening to text. Application Insights `traces` rows carry `timestamp`, `message`, and
`customDimensions`, and invocation IDs may live in `customDimensions` rather than in the message
string. A parser typed on `str` would discard the correlation data at the door and force a
rewrite later. Correlation logic should read `fields` first and fall back to parsing `message`.

**FR-3 — Viewer serving**
`funcviz view` serves a single static HTML asset on a local port and opens a browser. The viewer
loads a trace JSON. It must also work by opening the HTML file directly with a trace pasted or
selected, so a saved demo survives without the CLI.

### 5.1 Azure as an input source (v0.2 candidate, designed for now)

Local-only input caps the project's reach at the population that least needs it. Someone running
a function on their own laptop can read the log. Someone hitting a worker failure in production
cannot, and that is where the tool would actually be used.

The intended v0.2 path keeps the v0.1 file-input model intact and adds no authentication, SDK
dependency, or connector:

```
az monitor app-insights query --analytics-query "traces | where ..." -o json > prod.json
funcviz parse --from-appinsights prod.json -o trace.json
```

The user brings the query result; `funcviz` stays an offline parser. Because App Insights carries
the same host log output, the event-mapping rules built for v0.1 should largely transfer.

**This is not built in v0.1.** The only v0.1 obligation is FR-2's record shape, so that adding the
adapter later is an addition rather than a rewrite. Nothing else in this document changes for it.

Distinguish this from *visualizing Azure itself* — ARM calls, Sync Triggers, storage and
deployment topology, hosting-plan matrices. That is control-plane visualization, a different
product with a different data source and a different UI axis. It stays in `IDEAS.md` (§18).

---

## 6. Trace Schema

Phase 0 changed three things about the v1 schema sketch: correlation is not a single ID but three
distinct ones, duration is not a single number but several values from different sources, and lane
population is itself information that must be represented (an empty lane in a failure trace is a
finding, not a blank).

```json
{
  "schemaVersion": "0.1",
  "traceId": "trace-001",
  "outcome": "success",
  "input": {
    "source": "core-tools-log",
    "adapter": "CoreToolsLogAdapter",
    "adapterVersion": "0.1"
  },
  "runtime": {
    "environment": "local",
    "language": "python",
    "trigger": "http",
    "coreToolsVersion": "TBD",
    "hostVersion": "TBD"
  },
  "application": {
    "functionName": "hello",
    "sourceFile": "function_app.py",
    "sourceText": "...",
    "definitionLineRange": [5, 8]
  },
  "lanes": {
    "client":        { "status": "reached",     "confidence": "inferred", "reason": "Derived from host HTTP request/response lines." },
    "host":          { "status": "reached",     "confidence": "observed" },
    "python-worker": { "status": "reached",     "confidence": "observed" },
    "application":   { "status": "reached",     "confidence": "inferred", "reason": "User-code entry/exit is not separately logged." }
  },
  "events": [
    {
      "id": "e1",
      "sequence": 1,
      "timestamp": "2026-09-05T00:45:17.206Z",
      "elapsedMs": 0,
      "lane": "host",
      "event": "InvocationStarted",
      "httpRequestId": "2d0db691-...",
      "workerRequestId": "e42785bf-...",
      "invocationId": "6a8f3658-...",
      "correlation": {},
      "confidence": "observed",
      "attributes": {},
      "raw": "..."
    }
  ],
  "intervals": [
    {
      "id": "i1",
      "label": "Invocation (host log delta)",
      "lane": "host",
      "kind": "invocation",
      "startEvent": "e1",
      "endEvent": "e2",
      "durationMs": 34,
      "source": "log-delta",
      "confidence": "observed",
      "attributes": {},
      "raw": null
    },
    {
      "id": "i2",
      "label": "Invocation (host-reported)",
      "lane": "host",
      "kind": "invocation",
      "startEvent": "e1",
      "endEvent": "e2",
      "durationMs": 54,
      "source": "host-reported",
      "confidence": "observed"
    },
    {
      "id": "i3",
      "label": "HTTP request",
      "lane": "client",
      "kind": "http",
      "startEvent": "e0",
      "endEvent": "e3",
      "durationMs": 294,
      "source": "http-reported",
      "confidence": "inferred"
    }
  ],
  "failures": [],
  "metadata": {}
}
```

**Correlation — three IDs, kept separate (FR-4.1).** Every event carries up to three optional
identifier fields, never collapsed into one:

- `httpRequestId` — host HTTP pipeline id (`"requestId"` in the `Executing/Executed HTTP request` blocks).
- `workerRequestId` — worker gRPC channel/session id (`Request ID:`), spanning the whole worker
  session, startup and invocation alike. **Do not derive `traceId` from it** — it is a session span,
  not a per-invocation key.
- `invocationId` — per-invocation id (`invocation ID:` / `Id=`), present on both the host and worker
  invocation lines. This is the key that makes the Host↔Worker boundary correlatable.

`correlation` is a reserved generic map for identifiers a future adapter surfaces that do not map to
the three named fields (e.g. App Insights `operation_Id`). It is an escape hatch, **not** a
replacement for the named fields — new inputs still populate the named fields when they can.

**Intervals — a separate array, referenced by event `id` (FR-4.2).** There is no single canonical
duration. Each interval names its `source`:

- `source`: `log-delta` | `host-reported` | `http-reported` | `inferred` | `provider-reported`
- `kind`: e.g. `invocation` | `http` | `worker-startup`
- Intervals reference events by `id`, not by `sequence`. The viewer's default bar should prefer
  `log-delta`, but it must always label which source the displayed duration came from. The same
  invocation legitimately shows 34ms (log-delta), 54ms (host-reported), and 294ms (http-reported);
  presenting one as "the" duration would be a fabrication.

**Lanes — top-level status metadata (FR-4.3).** `lanes` records, per lane:

- `status`: `reached` | `not-reached` | `failed-here` | `unknown`
- `confidence`: `observed` | `inferred`
- `reason` (optional) and `failureEvent` (optional, an event `id`)

This is what lets a failure trace render the Client and Application lanes as a deliberate,
explained `not-reached` grey rather than an empty column that looks like a rendering bug.

**Field notes:**

- `lane`: `client` | `host` | `python-worker` | `application`
- `confidence`: `observed` | `inferred` (`instrumented` is reserved but unused in v0.1)
- `outcome`: `success` | `failure`
- `application` is always `inferred`: user-code entry/exit is not separately logged, so the lane is
  a window rendered muted/dashed with a badge. Events are never fabricated to fill it.
- `input` records which adapter produced the records; `metadata`, `attributes`, and `failures` are
  extension points intentionally present in v0.1 so v0.2 adapters add rather than rewrite.
- Runtime versions are recorded because the parser is coupled to log text. A trace without them is
  not reproducible.

**FR-4 — Confidence is load-bearing, not decorative.** Any event the parser did not read directly
from a log line is `inferred` and the viewer must render it visibly differently. This is the one
rule that keeps the tool from becoming an animation of an assumption.

---

## 7. Viewer

Three runtime lanes plus an application source panel:

```
┌─────────────────────────────────────────────────────────────┐
│ funcviz — hello · success · 54ms                            │
├───────────────────────────────┬─────────────────────────────┤
│ CLIENT   HOST    WORKER       │ function_app.py             │
│   │       │        │          │                             │
│   ├──────▶│        │          │  1  import azure.functions   │
│   │       ├───────▶│          │  2                          │
│   │       │        ●          │  5  @app.route(route="hello")│
│   │       │        │          │ ▶6  def hello(req):         │
├───────────────────────────────┴─────────────────────────────┤
│ InvocationStarted · host · +0ms · observed                  │
│ invocationId 6a8f3658                                       │
├─────────────────────────────────────────────────────────────┤
│ ◀ Prev    ▶ Play    Next ▶    ↺ Reset                       │
│ raw: [2026-09-05T06:43:12.184] Executing 'Functions...'     │
└─────────────────────────────────────────────────────────────┘
```

**FR-5 — Lanes.** Client, Host, and Python Worker are visually distinct columns. The active step
is highlighted. Inferred transitions are rendered distinguishably from observed ones.

**FR-6 — Application source panel.** The executed function's source file is displayed beside the
timeline. When the trace enters the `application` lane, the function definition block is
highlighted. Line-level stepping is **not** in v0.1 — only the definition block.

**FR-7 — Playback.** Previous, Next, Play, Pause, Reset. Replay is deterministic; Play is a timed
walk over the same ordered event list, not a re-simulation.

**FR-8 — Step detail and raw log.** The selected event shows its name, lane, timestamp, elapsed
time, invocation ID, confidence, and the original log line. The raw line is always reachable in
one interaction. This is the trust mechanism: a viewer who doubts the visualization can check it
against the source text immediately.

**FR-9 — Failure rendering.** A trace with `outcome: "failure"` terminates the timeline at the
last observed event and marks the stopping point in its lane, using that lane's `failed-here`
status. The viewer must not draw speculative continuation past the failure.

**FR-9.1 — Unreached lanes.** A failure can leave entire lanes empty. In the shipped
`worker-fail.log`, the worker fails to index functions before any request is served, so no
invocation, client, or HTTP events exist at all — the Host lane ends in `failed-here` and the
Client and Application lanes are `not-reached`. The viewer must render an unreached lane as a
deliberate, explained grey state driven by the `lanes[].status` metadata (§6), never as a blank
column that reads as a rendering failure. An empty lane is a finding the tool is meant to show.

---

## 8. Phase 0 — Discovery (do this first; nothing else starts until it is done)

This is the only task that cannot be delegated to an agent, because it requires running the
runtime and reading what actually comes out.

**Task 0.1** Build a minimal Python v2 HTTP-trigger app (the §14 sample). Run `func start
--verbose`. Capture full stdout/stderr to a file. Record Core Tools and host versions.

**Task 0.2** Trigger one request. Then produce a failure: break worker startup (for example, an
import error in `function_app.py`, or an invalid `requirements.txt`) and capture that log too.

**Task 0.3** Try raising `logging.logLevel` in `host.json` for worker-channel and gRPC categories
(e.g. `Microsoft.Azure.WebJobs.Script.Grpc`) and Python worker debug logging. Record whether this
exposes any Host↔Worker transition that default verbose output does not.

**Task 0.4** Fill in the event coverage matrix. **No event may be marked supported without a real
log line pasted next to it.**

| Desired event | Log line present? | Correlatable to invocation ID? | Verdict |
|---|---|---|---|
| HTTP request received | | | |
| Invocation created | | | |
| Worker selected / available | | | |
| Invocation sent to worker | | | |
| Invocation received by worker | | | |
| Application function started | | | |
| Application function completed | | | |
| Invocation response returned | | | |
| Invocation completed | | | |
| HTTP response returned | | | |
| Worker init failure | | | |

**Deliverables:** `examples/python-http-trigger/`, `samples/success.log`, `samples/worker-fail.log`,
`docs/event-coverage.md`.

The final v0.1 event list is whatever survives this matrix. The list in §7 is a hypothesis.

---

## 9. Resolved: The Host↔Worker Boundary Is Observable (under elevated logging)

The three-lane design assumed the logs distinguish Host activity from Python worker activity. This
was the single point on which the product concept rested, and **Phase 0 confirmed it** (see
`docs/event-coverage.md`).

The boundary is directly correlatable: the same `invocationId` appears on both the host's
`Executing 'Functions.hello' ... Id=...` line and the worker's `Received FunctionInvocationRequest
... invocation ID: ...` line. The worker lane is populated from observed events, not inferred ones.

The one condition is capture configuration (§5): the worker and gRPC log categories must be
elevated in `host.json` and `PYTHON_ENABLE_DEBUG_LOGGING` must be set. With plain `func start
--verbose` the worker lane is empty — which the schema represents honestly as a `not-reached` /
`unknown` lane status rather than by fabricating events. The only genuinely inferred lane is
`application` (user-code entry/exit is not separately logged); see §10.

---

## 10. Where Inference Still Applies

Phase 0 (§9) removed the worst case — the worker lane is observed, not inferred, when capture is
configured correctly. Two narrower inference situations remain, and both are handled by schema-backed
per-lane cues, summarized by a top-level "trace confidence boundary" banner derived from those same
`lanes[].confidence` / `lanes[].status` fields.

**The `application` lane is always inferred.** User-code entry and exit are not separately logged,
so this lane is a window between the worker's invocation receipt and the host's completion. It is
rendered muted/dashed with an explicit `inferred` badge and an `application` lane `reason`. Events
are never fabricated inside it.

**Un-elevated captures leave the worker lane unobserved.** If a log was produced without the §5
elevated configuration, the worker lane is simply `not-reached` / `unknown` in `lanes[].status` —
the viewer states that plainly ("Worker activity was not captured; re-run with elevated worker/gRPC
logging") rather than inventing inferred worker events to fill the column.

Reporting exactly how much of the runtime the logs let you see — and where they go dark — is a more
useful and more honest thing to publish than a confident diagram. It is also the standing argument
for the v0.2 OpenTelemetry input.

---

## 11. Budget and Cut Line

| Weekend | Work |
|---|---|
| 1 | Phase 0 discovery (manual). Freeze event list. Freeze schema. Parser skeleton with success log. |
| 2 | Viewer: three lanes, source panel, step detail, raw log, step controls. |
| 3 | Failure trace. Packaging, README, PyPI release. |

**Cut in this order if over budget.** Decided now, so it is not decided under pressure:

1. `Play` / `Pause` — ship step-only navigation
2. Automatic parsing of the failure log — ship the failure trace as a hand-verified fixture
3. Definition-block highlighting — ship the source panel as static display

**Never cut**, because removing any of these removes the reason the tool exists: the three lanes,
the raw-log inspection path, the `confidence` field, and schema versioning.

---

## 12. Risks

**R1 — Log text changes between Core Tools versions.** The parser is coupled to English log
strings. Mitigation: isolate all patterns in one module, record runtime versions in every trace,
keep captured sample logs as parser fixtures, and treat a version bump as a test run.

**R2 — Too much of the trace is inferred.** Mitigation: §10. Report the gap instead of papering
over it.

**R3 — Scope reopening.** Mitigation: §4 is a closed list. Anything not on it goes to `IDEAS.md`,
including ideas that arrive mid-implementation and feel small.

**R4 — Duration has multiple sources, not one value.** The invocation reports three different
durations depending on where you read it: a host-log timestamp delta (~34ms), the host's own
`Duration=54ms`, and the HTTP request/response block (294ms). Collapsing these into one number
misrepresents the data. Mitigation: the `intervals[]` schema (§6) records each duration separately
with an explicit `source`, and the viewer always labels which source a displayed duration came
from. Where a gap is genuinely unresolvable at millisecond granularity, do not render a
misleadingly precise number.

**R5 — Thin OSS demand.** Local-only input caps reach; most people with a real problem are in
production. Mitigation: §5.1 — the Application Insights adapter is the planned answer, and FR-2
makes it cheap. Build it when v0.1 exists and someone asks, not before.

---

## 13. Naming (decided)

The repository is `azure-functions-runtime-visualizer`. The CLI is `funcviz`.

Alternatives considered and rejected: `azure-functions-trace-viewer` (matches the existing
`azure-functions-*` family, but "trace" reads as distributed tracing / OpenTelemetry and would
misdirect expectations before the v0.2 OTel input exists) and `functions-log-timeline` (most
literal, weakest discoverability).

The name describes the destination rather than the v0.1 state, which is the right trade for a
project whose primary goal is public reach. The accuracy obligation it creates is discharged in
the product, not the name: §10 requires the viewer to state plainly which lanes are observed and
which are inferred. That banner is what keeps the name from becoming an overclaim, so it is on
the never-cut list in §11.

---

## 14. Demo Application

```python
import azure.functions as func

app = func.FunctionApp()

@app.route(route="hello")
def hello(req: func.HttpRequest) -> func.HttpResponse:
    name = req.params.get("name") or "Azure"
    return func.HttpResponse(f"Hello, {name}!")
```

---

## 15. Repository Structure

```
azure-functions-runtime-visualizer/
├─ src/funcviz/
│  ├─ parser/          # pure: Iterable[str] -> Trace
│  ├─ cli.py
│  └─ viewer/          # single static HTML asset
├─ schemas/trace-0.1.json
├─ examples/python-http-trigger/
├─ samples/            # captured raw logs (parser fixtures)
├─ traces/             # success.json, worker-fail.json
├─ docs/event-coverage.md
├─ IDEAS.md
└─ PRD.md
```

---

## 16. Security

Traces embed raw log text and may be shared in presentations or attached to issues. Before any
trace leaves the machine, `funcviz` must mask, at minimum: authorization headers, function keys,
connection strings, and storage credentials.

v0.1 implements masking as a parse-time regex pass with a `--no-mask` opt-out. Anything masked is
replaced with a visible marker, never silently dropped — a trace that quietly lost content is
worse than one that shows a redaction.

---

## 17. Acceptance Criteria

v0.1 ships when all of the following are true:

1. `docs/event-coverage.md` exists with real log lines as evidence for every supported event.
2. A real successful invocation parses into a valid `trace.json`.
3. A real worker-failure log parses into a valid failure trace.
4. Event order in the replay matches the log order.
5. Client, Host, and Worker are visually distinct; inferred events are visually distinct from
   observed ones.
6. The application source file is displayed beside the timeline.
7. Step forward, step backward, and reset work; replay is deterministic.
8. The original log line for any step is reachable in one interaction.
9. Masking is applied by default.
10. `pip install` → `funcviz view traces/success.json` works on a clean machine.
11. The saved traces can carry an SME presentation with no live invocation.

---

## 18. Deferred

**Designated v0.2 candidates.** Not built in v0.1, but v0.1's design accommodates them, so they
are named here rather than left to `IDEAS.md`:

- Application Insights input adapter (§5.1) — the primary answer to R5
- OpenTelemetry input via `"telemetryMode": "OpenTelemetry"` — structurally better data than log
  text, and the natural response if §10's fallback is triggered
- Line-level application tracing via `sys.settrace`

**Uncommitted.** Recorded in `IDEAS.md`, requiring their own justification if ever raised: storage
and deployment topology, hosting-plan awareness, additional triggers and language workers, Azure
control-plane visualization, Sync Triggers, host or worker instrumentation, a failure-pattern
trace library.

Everything in both lists requires v0.1 to exist and to have been used at least once by someone
other than the author.

---

## 19. Decision Log

- Purpose is a public OSS project; budget is 2–3 weekends. Both constrain scope simultaneously.
- The tool reads logs. It does not run, wrap, or manage the Functions host.
- Input is a file or stdin. Local Core Tools verbose output only in v0.1.
- Azure is in scope as a future *input source* (App Insights query results), not as a
  visualization target. Control-plane visualization stays uncommitted.
- The parser takes `LogRecord`, not `str`, so that structured Azure fields survive the boundary.
  This is the only v0.1 concession made for a v0.2 feature.
- Log-text parsing is the v0.1 data source. OpenTelemetry is deferred, not rejected.
- Python package with a local static viewer, distributed on PyPI.
- v0.1 ships one success trace and one failure trace.
- Three lanes: Client, Host, Python Worker.
- The Host↔Worker boundary is confirmed observable via a shared `invocationId`, provided capture
  elevates worker/gRPC log categories and sets `PYTHON_ENABLE_DEBUG_LOGGING` (§5, §9).
- Correlation is three separate IDs — `httpRequestId`, `workerRequestId`, `invocationId` — never
  collapsed; `correlation` is a reserved escape-hatch map for future adapters (§6).
- Duration is not a single value: intervals are recorded separately with an explicit `source`
  (log-delta / host-reported / http-reported / inferred / provider-reported) (§6, R4).
- Lane population is itself data: `lanes[].status` (reached / not-reached / failed-here / unknown)
  drives honest rendering of empty lanes in failure traces (§6, FR-9.1).
- The application source panel stays in v0.1; line-level tracing does not.
- No Host or Python worker modification in any released version without a proven, documented gap.
- Discovery precedes schema; schema precedes parser; parser precedes UI.
