# Sample logs (parser fixtures)

These raw `func start --verbose` logs are the parser's regression fixtures. Preserving the original
runtime text is the PRD R1 mitigation: the golden traces in `../traces/` are regenerated from these,
so a Core Tools log-format change surfaces here first.

## Provenance

| File | Origin | Trigger scenario |
|---|---|---|
| `success.log` | **Real capture** | Successful HTTP invocation of `hello` |
| `worker-fail.log` | **Real capture** | Worker fails to index (`ModuleNotFoundError`) |
| `invocation-fail.log` | ⚠️ **Synthetic** — hand-edited from `success.log` (`Succeeded`→`Failed`, `"status": "200"`→`"500"`) | In-invocation failure |
| `worker-unobserved.log` | ⚠️ **Synthetic** — `success.log` with the worker-side lines removed | Worker lane unobservable (log levels not elevated) |

## Why the synthetic ones are flagged

PRD §7.2 ("do not simulate what is measurable") and acceptance criteria AC2–AC3 call for a **real**
successful invocation and a **real** failure log. The two synthetic fixtures above assert the parser
against an edited input, not against text a real runtime emitted — so their failure/unknown
regression tests currently validate an assumption about the log shape rather than the shape itself.
A real thrown exception, for instance, is likely to emit more than one `Executed ... (Failed, ...)`
line (stack trace, `Exception while executing function`, worker-side error), which an edited success
log cannot reveal.

They are kept only as placeholders and must be replaced by real captures produced the same way as
Phase 0 (capture → save here → record the real lines as evidence in `../docs/event-coverage.md`).
Until then, treat any parser behavior that depends solely on these two files as unverified.
