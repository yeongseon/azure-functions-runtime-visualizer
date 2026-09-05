# Changelog

All notable changes to `funcviz` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-09-05

First public release.

### Added

- Pure-Python (stdlib-only, zero runtime dependencies) parser that turns Azure
  Functions verbose runtime logs into a versioned trace JSON.
- Three-lane execution timeline (Client / Functions Host / Python Worker) plus an
  application source panel, rendered by a self-contained static HTML viewer.
- One success trace and one worker-startup-failure trace, each event carrying a
  `confidence` field (`observed` vs `inferred`) and its original log line.
- CLI: `funcviz parse`, `funcviz view`, and `funcviz record`.
- Secret masking on by default (`--no-mask` to opt out): Authorization headers,
  function keys, and connection-string credentials are replaced with visible
  typed markers, never silently dropped.
- Confidence boundary banner in the viewer distinguishing observed from inferred
  activity.
- PyPI packaging via hatchling; the static viewer asset ships inside the wheel.

[0.1.0]: https://github.com/yeongseon/azure-functions-runtime-visualizer/releases/tag/v0.1.0
