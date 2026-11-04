# AirPods Handoff — Codex repository instructions

This is an experimental NixOS AirPods audio-ownership project. Read only the files relevant to the current task, rather than the entire repository.

Core invariants:
- Never claim this implements official Apple iCloud Automatic Switching or authenticated Apple host identity.
- Do not add repeated Bluetooth disconnect/connect cycles or compete with other AACP daemons.
- Preserve established Linux communication ownership against incidental iPhone activity, subject to known firmware limitations.
- Treat remote call/unknown as unsafe to seize; stale events and late ACKs must not override newer intent.
- Distinguish AACP ownership acknowledgment, BlueZ transport, PipeWire sink readiness, and audible sound; they are not equivalent.
- Recovery must be bounded, race-aware, and must not silently reset user-selected microphones or pairing.
- Preserve NixOS declarative integration and account for Zig vendor changes.
- Never claim hardware verification if only automated tests ran.

Use docs/agent-state/STATE.md as a small cross-account status index; read module-specific references only as needed. Keep AGENTS.md short; invoke task-specific skills rather than loading all skill files.

Before changes: inspect relevant code, establish a narrow plan and acceptance criteria. After changes: run the most relevant tests available, identify tests not run and hardware uncertainty. Do not make unrelated edits. Do not write secrets, Bluetooth keys, or sensitive diagnostic contents into shared state.

Project-level skills are in .agents/skills. Invoke explicitly with $handoff-debug, etc. when appropriate.
