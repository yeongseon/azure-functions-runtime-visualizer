# Event Coverage Matrix (Phase 0)

This document is the **frozen output of Phase 0 discovery** (PRD §8). Every event marked
`supported` has a real log line pasted next to it as evidence. The v0.1 event list is whatever
survives this matrix — the hypothetical list in PRD §7 was a hypothesis and is now superseded by
what was actually observed.

## Capture environment

Recorded by running the demo app in `examples/python-http-trigger/` locally.

| Field | Value |
|---|---|
| Core Tools Version | `4.6.0+ab90faafcab539d63cd3d0ce5faf1bca4395fccc` (64-bit) |
| Function Runtime Version | `4.1045.200.25556` |
| Python worker version | `4.40.2` |
| Python | `3.12.14` |
| `azure-functions` (PyPI) | `1.25.0` |
| Extension bundle | `Microsoft.Azure.Functions.ExtensionBundle 4.37.1` |
| OS | macOS (darwin, arm64) |
| Programming model | Python v2 (`@app.route`) |
| Trigger | HTTP |
| Capture command | `func start --verbose > samples/success.log 2>&1` |

`host.json` raised the following categories to `Trace` to maximize boundary visibility
(PRD Task 0.3): `Microsoft.Azure.WebJobs.Script.Grpc`, `Worker`, `Host.Function.Console`.
`local.settings.json` set `PYTHON_ENABLE_DEBUG_LOGGING=1`.

Raw fixtures: `samples/success.log` (337 lines), `samples/worker-fail.log`.

---

## Headline finding — the Host↔Worker boundary IS observable and correlatable

PRD §9 posed this as the single open question the whole product rests on. **Answer: the boundary
is directly observable, and it correlates by invocation ID.** The §10 fallback (rendering the
worker lane as entirely inferred) is therefore NOT required for the invocation path.

Evidence — the same invocation ID `6a8f3658-2b31-4554-aa86-1ee32a9e679b` appears on both sides:

```
[00:45:17.206Z] Executing 'Functions.hello' (Reason='...', Id=6a8f3658-2b31-4554-aa86-1ee32a9e679b)          <- host
[00:45:17.227Z] Received FunctionInvocationRequest, request ID: e42785bf-..., function name: hello,
                invocation ID: 6a8f3658-2b31-4554-aa86-1ee32a9e679b, function type: sync, ...                 <- worker
[00:45:17.240Z] Executed 'Functions.hello' (Succeeded, Id=6a8f3658-2b31-4554-aa86-1ee32a9e679b, Duration=54ms) <- host
```

Correlation key precedence for the parser: prefer the explicit `invocation ID:` / `Id=` token in
`fields`/message; the host `Id=` and worker `invocation ID:` are the same GUID.

### Three distinct correlation-id namespaces (do NOT merge)

The logs carry **three** separate id namespaces with confusingly similar labels. A parser that keys
on a lowercased "request id" would wrongly merge the HTTP-layer id with the worker-channel id.

| Namespace | Label in log | Example value | Scope | Evidence |
|---|---|---|---|---|
| `httpRequestId` | `"requestId"` (HTTP JSON block) | `2d0db691-...` | one HTTP request/response pair | L323 (req), L332 (resp) |
| `workerRequestId` | `Request ID:` / `request ID` (worker lines) | `e42785bf-...` | the **whole worker gRPC channel/session** — spans init, metadata, load, AND the invocation | L50, L54, L55, L298, L299, **L329** |
| `invocationId` | `invocation ID:` (worker) / `Id=` (host) | `6a8f3658-...` | one function invocation | L328, L329, L330 |

Key correction to the earlier "two axes" framing: `workerRequestId` is **not** startup-only. The
same `e42785bf-...` that appears in `WorkerInitRequest` (L54) also tags `FunctionInvocationRequest`
(L329). That is precisely what lets the worker lane correlate to the invocation — the invocation
line carries BOTH `workerRequestId` (channel) and `invocationId` (this call). The Host↔Worker
boundary is observable via `invocationId` (host `Id=` == worker `invocation ID:`).

---

## Success path — event coverage

Line numbers refer to `samples/success.log`.

| Desired event | Log line present? | Correlatable? | Verdict | Evidence (line) |
|---|---|---|---|---|
| HTTP request received | Yes | by `httpRequestId` | **supported** | L322–L327 `Executing HTTP request: { "requestId": "2d0db691-...", "method": "GET", "uri": "/api/hello" }` |
| Invocation created (host) | Yes | by `Id=` (invocationId) | **supported** | L328 `Executing 'Functions.hello' (Reason='...', Id=6a8f3658-...)` |
| Invocation received by worker | Yes | by `invocation ID:` + `workerRequestId` | **supported** | L329 `Received FunctionInvocationRequest, request ID: e42785bf-..., ... invocation ID: 6a8f3658-...` |
| Application function started | No (not separately logged) | — | **inferred** | No distinct "user code entered" line; inferred at worker receipt (L329). User `logging` lines would appear here if present. |
| Application function completed | No (not separately logged) | — | **inferred** | Inferred at host completion (L330). |
| Invocation completed (host) | Yes | by `Id=` + Duration | **supported** | L330 `Executed 'Functions.hello' (Succeeded, Id=6a8f3658-..., Duration=54ms)` |
| HTTP response returned | Yes | by `httpRequestId` + status | **supported** | L331–L336 `Executed HTTP request: { "requestId": "2d0db691-...", "status": "200", "duration": "294" }` |

### Boot / worker-startup events (observed, correlate by `workerRequestId`)

All boot events share the worker-channel id `e42785bf-...` — the same id that later tags the
invocation (L329), so it is a session-scoped `workerRequestId`, not a startup-only key.

| Event | Verdict | Evidence (line) |
|---|---|---|
| Worker process launch | **supported** | L49 `INFO: Starting Azure Functions Python Worker.` |
| Worker identity assigned | **supported** | L50 `INFO: Worker ID: f17a18d1-..., Request ID: e42785bf-..., Host Address: 127.0.0.1:56863` |
| gRPC channel opened | **supported** | L51 `INFO: Successfully opened gRPC channel to 127.0.0.1:56863` |
| Worker init | **supported** | L54 `Received WorkerInitRequest, python version 3.12.14 ..., worker version 4.40.2, request ID e42785bf-...` |
| Worker metadata request | **supported** | L55 `Received WorkerMetadataRequest, request ID e42785bf-..., function_path: .../function_app.py` |
| Function app indexed | **supported** | L56 `Indexed function app and found 1 functions` |
| Function metadata processed | **supported** | L57 `Successfully processed FunctionMetadataRequest for functions: Function Name: hello, ...` |
| Worker process ready | **supported** | L297 `Worker process started and initialized.` |
| Function load | **supported** | L298–L299 `Received WorkerLoadRequest, request ID e42785bf-..., function_name: hello, ...` |
| Host route mapped | **supported** | L312 `Mapped function route 'api/hello' [all] to 'hello'` |
| Job host started | **supported** | L316 `Job host started` |

---

## Failure path — event coverage

Line numbers refer to `samples/worker-fail.log`. Failure induced by adding
`import this_module_does_not_exist` to `function_app.py` (worker indexing failure at startup).

| Desired event | Log line present? | Verdict | Evidence (line) |
|---|---|---|---|
| Worker init failure (root cause) | Yes | **supported** | L57 `ERROR: Error: No module named 'this_module_does_not_exist', Cannot find module...` |
| User-code traceback | Yes | **supported** | L59–L74 Python traceback ending `L74 ModuleNotFoundError: No module named 'this_module_does_not_exist'` pointing at `function_app.py line 2` |
| Worker indexing failed | Yes | **supported** | L75 `Worker failed to index functions` |
| Result: Failure | Yes | **supported** | L76 `Result: Failure` / L78 `Exception: ModuleNotFoundError: ...` |
| Zero functions loaded | Yes | **supported** | L96 `0 functions found (Worker)` / L97 `0 functions loaded` |
| Host retry loop | Yes (observed) | **supported** | After L97 the host re-reads `host.json` (L106+) and retries indexing repeatedly. |

### Failure-rendering implication (PRD FR-9)

The failure trace terminates at the **last meaningful observed event before the retry loop**:
`Worker failed to index functions` / `Result: Failure` (L75–L78). The parser must NOT render the
subsequent retry churn as forward progress, and the viewer must not draw speculative continuation
past the failure. There is no invocation ID on this path (the app never indexed), so the failure
belongs to the **worker/startup** lane, not a per-invocation lane.

---

## Parser notes carried forward from Phase 0

1. **Multi-line JSON blocks.** `Executing HTTP request` / `Executed HTTP request` and the host
   option dumps (`LoggerFilterOptions`, `HttpWorkerOptions`, etc.) span many lines with the same
   timestamp prefix. The parser must reassemble these into one logical record, keyed by the
   `{`...`}` block, not treat each line as an event.
2. **Giant noise line.** `worker-fail.log` L56 (`Error in index_function_app. Sys Path... Sys
   Module: {...}`) dumps the entire `sys.modules` map on a single line (~kilobytes). Treat as noise
   / non-event; do not attempt to parse it as structured data.
3. **Three correlation IDs (not two axes).** Events carry up to three distinct identifiers, and the
   parser must keep them in separate fields:
   - `httpRequestId` — the host's HTTP pipeline id, labeled `"requestId"` inside the
     `Executing/Executed HTTP request` JSON blocks (`2d0db691-...`).
   - `workerRequestId` — the worker gRPC channel/session id, labeled `Request ID:` / `request ID`.
     It spans the **entire** worker session (startup **and** per-invocation lines, e.g. success.log
     L50/L54/L55/L298/L299 and the invocation line L329), so it is *not* a startup-only key
     (`e42785bf-...`).
   - `invocationId` — the per-invocation id, labeled `invocation ID:` / `Id=`, appearing on both the
     host `Executing 'Functions.hello' ... Id=...` and the worker `Received FunctionInvocationRequest`
     lines (`6a8f3658-...`). This is the key that makes the Host↔Worker boundary correlatable.
4. **Timestamp format.** `[2026-09-05T00:45:17.206Z]` — ISO 8601, millisecond resolution, UTC.
   Millisecond resolution is adequate, but note that the invocation has **three different durations
   from three different sources**, and they must not be collapsed into one "the" duration:
   - `log-delta` ~34ms — `Executing`(L328) → `Executed`(L330) timestamp difference.
   - `host-reported` 54ms — the host's own `Duration=54ms` on L330.
   - `http-reported` 294ms — the HTTP request/response block (L323 → L332).
   R4 is therefore a *source-provenance* problem, not a timestamp-resolution problem: each interval
   must be labeled with its `source`.
5. **Lane assignment heuristic (observed):**
   - `client`: derived from HTTP request/response host lines (the client itself does not log).
   - `host`: `Executing/Executed 'Functions.*'`, `Executing/Executed HTTP request`, host lifecycle.
   - `python-worker`: `Received *Request` lines, `Starting Azure Functions Python Worker`,
     `Successfully opened gRPC channel`, `Worker process started`.
   - `application`: inferred window between worker receipt and host completion (no dedicated line).

---

## Frozen v0.1 event list (survivors of the matrix)

Observed (render as `observed`):
`HttpRequestReceived`, `InvocationStarted`, `InvocationReceivedByWorker`, `InvocationCompleted`,
`HttpResponseReturned`, plus startup events `WorkerStarting`, `GrpcChannelOpened`, `WorkerInit`,
`FunctionAppIndexed`, `WorkerReady`, `JobHostStarted`, and failure events `WorkerIndexingFailed`,
`InvocationFailed`.

Inferred (render distinguishably, PRD FR-4):
`ApplicationFunctionStarted`, `ApplicationFunctionCompleted` (the `application` lane window).
