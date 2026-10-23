# AGENTS.md

## Scope

This repository maintains the Azure Functions Runtime Visualizer.
Preserve the distinction between observed trace evidence, inferred
causality, replay ordering and unsupported platform claims.

## PR Review and Merge Policy

Apply the same review standards regardless of whether work is authored
by a person or with OpenCode, Codex, Claude Code, ChatGPT, Copilot or
another coding agent. No particular AI reviewer is required.

1. Keep changes focused; add relevant parser, replay/UI and edge-case
   tests, documentation and validation evidence.
2. Use **GitHub CI** required checks on the final PR head as the
   authoritative automated result. Local tests/builds are recommended,
   not a separate merge gate. CI runner type is not prescribed.
3. Review correctness, trace privacy, data provenance, security,
   failure boundaries and maintainability. AI reviews are optional
   **advisory** inputs, not approval or test evidence.
4. Resolve or disposition findings. The responsible maintainer verifies
   required CI and decides on merging. Independently scrutinize any
   changes that expand network/trace-data access, workflow permissions,
   secrets or publication capabilities.

