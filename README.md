# Azure Functions Runtime Visualizer (`funcviz`)

Turn Azure Functions verbose runtime logs into an interactive, replayable execution timeline that
separates **Client**, **Functions Host**, and **Python Worker** activity — alongside the
application source file that was executed.

`funcviz` **reads logs**. It does not launch, wrap, or manage the Functions host. You run your
Function App with verbose logging, save the output, and `funcviz` turns it into a trace you can
step through and inspect line-by-line against the original log text.

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
func start --verbose > run.log

# 2. Parse logs into a trace
funcviz parse run.log -o trace.json

# 3. View the interactive timeline
funcviz view trace.json
```

Every event carries a `confidence` field (`observed` vs `inferred`) and its original log line, so a
viewer who doubts the visualization can check it against the source text in one interaction.

## What's honest about it

Phase 0 discovery (see [`docs/event-coverage.md`](docs/event-coverage.md)) confirmed against a real
local run that the **Host↔Worker boundary is directly observable and correlatable by invocation
ID** — the same GUID appears in both the host's `Executing 'Functions.hello' ... Id=...` line and
the worker's `Received FunctionInvocationRequest ... invocation ID: ...` line. The only inferred
lane is the `application` window (user-code entry/exit is not separately logged).

## Repository layout

```
examples/             # runnable demo Function App used for Phase 0
samples/              # captured raw logs (parser fixtures)
docs/event-coverage.md# Phase 0 evidence matrix (real log lines per event)
PRD.md                # product requirements + decision log
IDEAS.md              # deferred / uncommitted ideas

# planned (created as v0.1 lands):
src/funcviz/          # Python package: parser (pure) + CLI + static viewer
schemas/              # trace JSON schema (versioned)
traces/               # generated sample traces
```

## Scope (v0.1)

**In:** local Core Tools, Python worker, HTTP trigger, single invocation, replay only, one success
trace + one failure trace, PyPI package, local static viewer.

**Out (explicitly):** Azure connectivity, Application Insights, other triggers/languages, Durable
Functions, scale-out, host/worker modification, line-level tracing. See [`PRD.md`](PRD.md) §4.

## License

[MIT](LICENSE)
