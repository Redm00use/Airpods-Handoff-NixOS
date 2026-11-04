# Wait for call audio handoff before transport repair

Status: REJECTED after hardware validation; code reverted.

## Evidence and alternatives

The previous on-device quiet-Discord test produced three ownership recoveries and a stalled A2DP transport. An explicit sink suspend/resume later restored an audible diagnostic signal. Ownership acknowledgments preceded audio-source transitions; restarting immediately on a sink error can overlap the peer's release.

Reviewed primary implementations:

- [EarPort](https://github.com/Anoryth/earport/tree/68f73ebce6dc4f6ce78e4907baeff9080273c9d3): separates handoff policy from audio recovery and allows 1500 ms for peer release before restarting audio (`daemon/src/handoff.c`). Relevant protocol/timing evidence; no proof that it retains every silent PC call with our AAC/manual-choice requirements.
- [xatuke/handoff](https://github.com/xatuke/handoff/tree/4568bde): basic ownership/source handoff and reclaim-on-NONE logic. Replacing the current implementation would discard typed manual-route fencing, background control-only connection and broader lifecycle protection.
- [PodHop](https://github.com/Mur5h/PodHop/tree/d3a9732): explicit AACP takeover/release utility. It is not a replacement for the current call-ownership policy.
- [LibrePods](https://github.com/librepods-org/librepods/tree/89356c0): useful protocol/settings reference. The reviewed Linux tree does not establish a solution for quiet-call priority. Android-specific behavior is not automatically applicable to Linux.

References were inspected only. No replacement daemon or UI was installed; no GPL source was copied into this MIT project. The bounded timing behavior is implemented independently in the existing Python handler.

## Decision

In `Adapter.ensure_audio`, only a proven continuing local call whose source has not yet become local receives a bounded 1.5-second transfer-settling window. During that window, natural audio success avoids a repair. A changed context, manual iPhone selection, phone-call evidence or lost eligibility cancels it. Restart is allowed only after known local/no-source state with typed idle/media and remote idle; remote and unknown source states defer it.

Keep ordinary media-error recovery fast. Keep the existing repair and ownership budgets; add no reconnect loop, force ownership, HFP switch, microphone change or score-response echo. Do not interpret peer score-only `301` as a request without further evidence.

## Acceptance checks

- No suspend/resume before the call-settling window completes.
- Known idle release permits the existing single repair.
- Manual iPhone choice, phone call, hangup, generation change, unknown source and active peer cancel/defer repair.
- Natural local audio success requires no repair.
- Non-call media recovery has no new delay.

229 system Python tests passed, including four new regression scenarios. Portable Nix checks passed (232 Python tests and all four x86_64 flake checks); system build and activation passed. Only the handoff handler restarted. On-device validation repeated the same three ownership recoveries and final failed audio transport. The extra delay increased recovery time without fixing this failure, so the code and its four new tests were removed from the active tree. The experimental test source remains in local research artifacts. This change addresses transport restart ordering; it does not prove that firmware will stop changing ownership during a silent AAC call.

An explicit Return restored source=Linux and audio_active=true afterward; the user then exited the test call. The working system and original handler source were restored before the next experiment.
