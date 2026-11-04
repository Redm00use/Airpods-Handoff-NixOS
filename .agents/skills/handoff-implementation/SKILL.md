---
name: handoff-implementation
description: Implement a scoped, already-defined AirPods Handoff feature or bug fix across Zig, Nix, Python or Noctalia without unrelated refactoring.
---
1. Inspect the smallest impacted area and tests. List acceptance criteria before editing.
2. Preserve API/IPC and package/module compatibility unless explicitly changing them; account for vendored Zig controller interactions.
3. Prefer a minimal diff and a focused regression test. Avoid speculative platform workarounds and broad rewrites.
4. Run relevant checks; summarize what passed, failed and could not be tested. Link changed functions/files.
5. Update shared state only for durable decisions or next-action blockers; do not paste verbose tool logs.
