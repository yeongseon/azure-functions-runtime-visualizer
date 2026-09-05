# IDEAS

Uncommitted ideas. Anything here requires its own justification if ever raised, and requires v0.1
to exist and to have been used at least once by someone other than the author (PRD §18).

## Designated v0.2 candidates (design already accommodates them)

- **Application Insights input adapter** — `funcviz parse --from-appinsights prod.json`. The user
  brings an `az monitor app-insights query` result; `funcviz` stays an offline parser. Primary
  answer to the "thin OSS demand / local-only reach" risk (PRD R5). Cheap because the parser is
  typed on `LogRecord`, not `str`, so structured `customDimensions` survive the boundary.
- **OpenTelemetry input** via `"telemetryMode": "OpenTelemetry"` in `host.json` — structurally
  better data than log text (exports from both host and worker). Deferred because it requires the
  user to run an OTLP receiver, which breaks the "one command, no setup" property.
- **Line-level application tracing** via `sys.settrace` — step through user code line by line
  instead of only highlighting the definition block.

## Uncommitted (control-plane / out of product axis)

- Storage and deployment topology visualization
- Hosting-plan awareness (Consumption / Premium / Dedicated matrix)
- Additional triggers (queue, timer, Service Bus) and language workers (Node, Java, .NET)
- Azure control-plane visualization (ARM calls, Sync Triggers)
- Host or worker instrumentation
- A failure-pattern trace library
