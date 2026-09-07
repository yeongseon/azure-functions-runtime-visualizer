# Azure Functions Runtime Visualizer (`funcviz`)

[**Try the interactive demo on GitHub Pages →**](https://yeongseon.dev/azure-functions-runtime-visualizer/)

Turn Azure Functions verbose runtime logs into an interactive, replayable execution timeline that
separates **Client**, **Functions Host**, and **Python Worker** activity — alongside the
application source file that was executed.

![funcviz Azure Portal Light Presentation replaying a failed invocation: Client, Functions Host,
and Python Worker form the sequence above a shared Evidence row containing Step Detail, Error, and
Call Stack; one full-width Source Probe follows below, while replay is selected at the real +272 ms
application boundary](docs/hero-shared-evidence.png)

`funcviz` **reads logs**. It does not launch, wrap, or manage the Functions host. You run your
Function App with verbose logging, save the output, and `funcviz` turns it into a trace you can
step through and inspect line-by-line against the original log text.

The hosted demo uses an embedded sample trace. Files and pasted traces are processed only in your
browser and are not uploaded, but traces can contain raw log lines or embedded source code — review
them before sharing.

> **Status:** early development (v0.1 in progress). Local Azure Functions + Python + HTTP trigger,
> log-file input, replay-only. See [`PRD.md`](PRD.md) for the full scope and decision log.

## Why

Azure Functions runtime logs report *what* happened but not *where*. You can't tell from the text
alone which component was active, when control crossed from the Host into the language worker, or —
for a failure — how far the lifecycle got before it stopped. An ordered timeline with explicit
component ownership communicates this far faster than a log excerpt, which is exactly what support
engineers, SME presentations, and onboarding need.

## How it works

```bash
# 0. Install
pip install funcviz

# 1. Capture (you run this against your own Function App)
#    The Python Worker lane only populates when the worker log categories are
#    elevated in host.json (Microsoft.Azure.WebJobs.Script.Grpc / Worker /
#    Host.Function.Console = "Trace") and PYTHON_ENABLE_DEBUG_LOGGING=1 is set.
#    See PRD.md §5; examples/python-http-trigger/host.json already carries this.
func start --verbose > run.log

# 2. Parse logs into a trace, embedding the executed source for the source panel
funcviz parse run.log -o trace.json --source path/to/function_app.py

# 3. View the interactive timeline
funcviz view trace.json
```

Without the elevated log levels the Host and Client lanes still populate, but the Worker lane is
reported as `unknown` — a legitimate lane status, not a parser bug. `--source` is optional and
opt-in (it keeps the parser pure); omit it and the viewer's source panel shows a placeholder.

Every event carries a `confidence` field (`observed` vs `inferred`) and its original log line, so a
viewer who doubts the visualization can check it against the source text in one interaction.

### Production logs via App Insights export

For a deployed app, export a query result and parse it the same way — `funcviz` stays an offline
parser with no auth, SDK, or connector:

```bash
az monitor app-insights query --app <component> -g <rg> \
  --analytics-query "union traces, requests | where operation_Id == '<op-id>' | project timestamp, itemType, message, name, customDimensions | order by timestamp asc" \
  -o json > prod.json
funcviz parse prod.json --from-appinsights -o trace.json
```

App Insights ingests the host bookends but not the raw python-worker verbose lines, so the worker
lane is honestly `unknown` in traces built from an export; the client lane is absent by design.
Latency aggregation and performance analytics stay in App Insights (see
[`PRD.md`](PRD.md) §3.1) — a funcviz trace never becomes a dashboard.

## Try it now (no capture required)

The repo ships a real captured log, a demo Function App, and a ready-made trace, so you can
reproduce the full pipeline end-to-end without running your own Function App. From a clone
(`pip install -e .`, or run the module directly), the steps below produce exactly the outputs shown.

```bash
# Quickest path: view the trace that ships with the repo
funcviz view traces/success.json
```

Expected: a local static server prints `funcviz viewer: http://127.0.0.1:<port>/index.html`
(HTTP `200`), the page title is `funcviz — trace viewer`, and the **source panel is populated with
`function_app.py`** — no placeholder. The committed `traces/success.json` embeds the executed source
(`definitionLineRange` `[6, 9]`), so this works out of the box.

To regenerate that trace yourself from the raw log:

```bash
# 1. Parse the bundled success log, embedding the executed source for the panel
funcviz parse samples/success.log -o trace.json \
    --source examples/python-http-trigger/function_app.py
```

Expected `trace.json` (verified): `outcome: success`, `7` events, and four lanes —
`host` and `python-worker` are `observed`/reached, `client` and `application` are
`inferred`/reached. The `application` block carries the embedded source:

```jsonc
"application": {
  "sourceFile": "function_app.py",
  "sourceText": "…",           // the executed function_app.py, embedded verbatim
  "definitionLineRange": [6, 9] // the def hello(...) span
}
```

`--source` is optional and opt-in (it keeps the parser pure); omit it and the same trace renders
correctly but the viewer's source panel shows the "source not embedded" placeholder instead.

```bash
# Streaming variant: pipe a live run straight into a trace
func start --verbose | funcviz record -o trace.json
```

`record` reads stdin until EOF/Ctrl-C and writes the same schema-0.1 trace (verified: `7` events
from the bundled log).

## What's honest about it

Phase 0 discovery (see [`docs/event-coverage.md`](docs/event-coverage.md)) confirmed against a real
local run that the **Host↔Worker boundary is directly observable and correlatable by invocation
ID** — the same GUID appears in both the host's `Executing 'Functions.hello' ... Id=...` line and
the worker's `Received FunctionInvocationRequest ... invocation ID: ...` line. The only inferred
lane is the `application` window (user-code entry/exit is not separately logged).

## Repository layout

```
examples/             # runnable demo Function App used for Phase 0
samples/              # captured raw logs (parser fixtures); see samples/README.md
docs/event-coverage.md# Phase 0 evidence matrix (real log lines per event)
src/funcviz/          # Python package: parser (pure) + CLI + static viewer
schemas/              # trace JSON schema (versioned)
traces/               # generated sample traces
PRD.md                # product requirements + decision log
IDEAS.md              # deferred / uncommitted ideas
```

## Scope (v0.1)

**In:** local Core Tools, Python worker, HTTP trigger, single invocation, replay only, one success
trace + one failure trace, PyPI package, local static viewer.

**Out (explicitly):** Azure connectivity, Application Insights, other triggers/languages, Durable
Functions, scale-out, host/worker modification, line-level tracing. See [`PRD.md`](PRD.md) §4.

## License

[MIT](LICENSE)
