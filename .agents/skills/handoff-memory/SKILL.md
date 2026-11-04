---
name: handoff-memory
description: Compact a completed AirPods Handoff work session into repo-backed cross-account project memory, preserving decisions, evidence and next work without long chat transcripts.
---
1. Read current `docs/agent-state/STATE.md` and `git status --short`, `git log -1 --oneline`.
2. Update only durable, relevant facts: objective/status, decision with rationale, tested commands/results, unresolved hypotheses, regression risks, next action.
3. Record commit references when available. Replace obsolete status; do not grow an append-only transcript. Aim for a short index (preferably under ~200 lines).
4. Explicitly mark software-only vs hardware-verified findings and unrun tests.
5. Never store credentials, Bluetooth pairing keys, private paths or raw personal diagnostics. Do not commit without being asked.
