# Viewer redesign spec — timeline v2

Authoritative UI/interaction spec for the M2 timeline redesign. The M2 issues (#52–#62, #70, #71) reference the section numbers here. Where this document and older PRD wording disagree, this document wins for the viewer; PRD prose is reconciled separately (#63).

Guiding principle: the viewer must never make an *inferred* or *unknown* thing look like an *observed* fact, and it must never simulate a value it did not measure (PRD §7.2). Every visual affordance below exists to keep that honesty legible without a legend.

---

## 1. Layout — five horizontal bands

The frame is a vertical stack of bands, full width, time flowing **left → right**:

- **A — Header.** Trace identity + outcome (see §2).
- **B — Timeline.** The four lanes as horizontal swimlanes over a shared elapsed-time axis (see §3, §4).
- **C — Source.** gdb-style windowed view of the executed source (see §5).
- **D — Detail + stack.** Selected node detail and the call stack at the playhead (see §6).
- **E — Error + raw.** Error summary (when present) and the raw log line(s) backing the selection (see §7).

Bands are always present in the DOM. An absent section (e.g. no error) renders as an explicit empty state, not a collapsed/missing band — layout must not jump between success and failure traces (§11).

---

## 2. Header (band A)

### 2.1 Outcome chip
- The header carries a single outcome chip: `success` / `failed`.
- **A failure header must not lead with a duration.** Outcome is the headline; duration is secondary. For a failure, showing "312 ms" first implies a completed run — forbidden. Duration, if shown on a failure, is subordinate to the outcome and clearly framed as "reached failure at".

---

## 3. Lanes (band B — structure)

### 3.1 Four fixed lanes
Four rows, fixed order, always rendered even when empty:

1. `client` — *caller / HTTP*
2. `host` — *Functions host / dispatch*
3. `python-worker` — *language worker / gRPC*
4. `application` — *your function code*

Each lane shows a **role subtitle** (the italic text above) so a first-time viewer reads ownership without prior knowledge (#71). This is the lightweight always-on alternative to, and complements, the pre-play structure view (§10, #70).

### 3.2 Lane status treatments — `unknown` ≠ `not-reached`
Lane status ∈ `reached` | `failed-here` | `not-reached` | `unknown`. Treatments:

- `reached` — solid lane fill.
- `failed-here` — solid fill up to the failure point, failure marker at the stop.
- `not-reached` — **dashed** lane outline, empty interior. "Control never got here."
- `unknown` — **45° hatch** fill. "We can't see this lane because logs weren't elevated."

**`unknown` and `not-reached` must never share a treatment.** They mean opposite things: `not-reached` is a positive statement that control did not arrive; `unknown` is an absence of evidence. Conflating them would claim knowledge we don't have. No legend is required — hatch vs dashed must be self-evidently different (#56). `STATUS_LABELS` already carries the text labels; this issue is the *visual* separation, not the labels.

### 3.3 Outcome is separated from the event stream
The run outcome is expressed in the header (§2.1) and/or a dedicated outcome column at the right edge of the timeline — **not** as an inline "Run stopped" pseudo-node inside a lane (#55). Nodes represent observed/inferred lifecycle events; the outcome is a property of the whole run, rendered as such.

---

## 4. Time axis & connectors (band B — geometry)

### 4.1 Axis
- Single shared x-axis, elapsed time, left → right, `t0` at the first event.

### 4.2 Compression (display-only)
- A gap qualifying as compressible = **> 35% of the domain with no events**.
- A compressed gap collapses to a **fixed 48px band** with a **break marker** (axis break glyph).
- **Compression is display-only.** Every number shown in the detail panel and tooltips is the *real* delta, never the compressed distance. The axis may lie about spacing; the readouts must not.

### 4.4 Node shapes — observed vs inferred
- `observed` event → **filled** node.
- `inferred` event → **hollow, dashed-outline** node.
Node shape alone must communicate provenance, so the confidence banner can shrink (§ banner, #61).

### 4.5 Connectors — three treatments
1. **Same-lane progression** → thin line, **no arrowhead**. (Sequential steps within one component are not "handoffs".)
2. **Observed cross-lane handoff** → **solid line with arrowhead**. (e.g. host → worker, correlated by invocation ID.)
3. **Inferred transition** → **dashed line with arrowhead**.

The `python-worker → application` connector is **always dashed** (arrowhead) — user-code entry is inferred, never directly logged (#54).

---

## 5. Source panel (band C) — gdb-style window

### 5.1 Windowing
- Show a **fixed-height** window centered on the focus line: **focus ± 4 lines**.
- Lines outside the window collapse into **"… N lines above / below"** counts, gdb-style — the panel never grows to the full file (#57).

### 5.3 Confidence on the source highlight
- The highlighted source line/range is a *heuristic* match (the parser does not get a line number from the runtime), so it must be labeled **inferred**.
- **Never highlight a source line without an accompanying confidence label row** stating the match is inferred (#58). The schema touchpoint for this is §9.

---

## 6. Detail + stack (band D)

### 6.1 Detail
- Selected-node detail: component, event, **real** timestamp/delta (§4.2), confidence, and a pointer into the raw log (band E).

### 6.2 Stack panel
- A call-stack view at the current playhead, innermost first:
  - `#0 python-worker`
  - `#1 host`
- Frames reflect which components are active at the playhead; it updates as the playhead moves (#59, §8).

---

## 7. Error + raw (band E)
- Error summary when the trace has a failure (message + failing component), else an explicit empty row (§11).
- The raw log line(s) backing the current selection, so a skeptic can verify any node against source text in one interaction.

---

## 8. Replay — playhead moves, nodes don't
- Replay advances a **playhead** left → right across the fixed axis.
- **Nodes do not move and do not relayout.** They change *state* (pending → active → done) as the playhead passes. Relayout-on-play is forbidden — it destroys the viewer's spatial memory (#60).
- Compressed spans (§4.2) play through in a fixed **400 ms**, regardless of their real (large) duration.
- A live elapsed counter shows **real** elapsed time during replay (not compressed time).

---

## 9. Schema touchpoints
- Source-highlight confidence (§5.3) needs a schema home. Preferred (option b): add `failures[].sourceLine` plus an optional `confidence` on the highlight, so the viewer renders the inferred label from data rather than hardcoding it.
- Any new field is additive and optional; schema stays 0.1-compatible for existing traces.

---

## 10. Pre-play structure view
- Before replay starts, show a **static 4-component structure**: the four lanes with their role subtitles (§3.1) and their pre-run status, so the viewer understands the topology before any motion (#70).

---

## 11. Acceptance criteria
1. Lanes render as horizontal swimlanes on a shared L→R elapsed-time axis; no vertical-column layout remains.
2. All four lanes are always present, in fixed order, with role subtitles.
3. Same-lane connectors have no arrowhead; cross-lane observed handoffs are solid arrows.
4. `worker → application` is a dashed arrow in every trace.
5. `unknown` (hatch) and `not-reached` (dashed) are visually distinct with no legend.
6. `observed` nodes are filled; `inferred` nodes are hollow/dashed.
7. A failure header does not lead with a duration; outcome is the headline.
8. Axis compression is display-only; detail/tooltip always show the real delta; compressed spans carry a break marker.
9. The source panel is a fixed-height ±4-line window with collapsed counts; a highlighted line always carries an inferred-confidence label.
10. Replay moves a playhead; nodes keep their positions and only change state; a live real-time counter is shown.
11. The success trace holds the same frame (empty error row, live application lane) with no layout jump relative to a failure trace.
