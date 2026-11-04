---
name: handoff-context
description: Recover essential state when starting a new Codex session/account or switching tasks in the AirPods Handoff NixOS repository. Not for ordinary small edits.
---
1. Check `git status --short`, `git log -1 --oneline`, then read `docs/agent-state/STATE.md` and this repository's `AGENTS.md`.
2. Identify the requested subsystem; consult only matching source files, tests and README sections. Prefer targeted `rg` searches to bulk reading.
3. Separate verified repository facts, remembered decisions, hypotheses, and current user requests. Verify stale state against current HEAD.
4. Return a compact briefing: objective, relevant modules, protected invariants, known uncertainties, next action. Do not replay historical discussions.
