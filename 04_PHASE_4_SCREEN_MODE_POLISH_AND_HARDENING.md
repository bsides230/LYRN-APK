# Phase 4 Prompt — Screen Mode Polish and Interaction Hardening

Work only on Phase 4.

Before doing anything:
- read `00_CONTROL_PROMPT.md`
- read all prior build notes
- do not reopen earlier architecture unless needed to fix a real issue

## Objective

Polish Screen mode so it feels like a true display appliance and not just a normal app route.

This phase is focused on UX hardening, display stability, and preventing accidental disruption while preserving a clean architecture.

## Scope

Build the following as appropriate to the existing implementation:

- keep-screen-on behavior for Screen mode
- stronger fullscreen or immersive handling where needed
- reduced accidental navigation or interaction
- viewer-oriented polish for display usage
- reconnection/reload behavior if appropriate
- any minimal, intentional escape/reset path for maintenance access

## Screen Mode Principles

Screen mode should feel:
- stable
- deliberate
- low-friction
- hard to accidentally break
- visually clean
- suitable for signage, display panels, or passive monitoring surfaces

## Acceptable Enhancements

If justified by the current architecture, you may add:
- hidden maintenance entry path
- simple unlock action
- reload/reconnect controls that are intentionally tucked away
- suppression of unnecessary gestures or controls
- route protections appropriate for viewer mode

Keep everything simple and explain all decisions in the build notes.

## Do Not Do

- do not turn this into a full MDM or enterprise kiosk product
- do not add speculative admin systems
- do not add excessive native complexity for edge cases not yet needed
- do not muddy Remote mode with Screen-only behavior

## Deliverable Standard

At the end of Phase 4, Screen mode should feel like a proper LYRN display node while Remote mode remains the full interactive control-surface experience.

## Completion Checklist

Only mark this phase complete when all are true:

- [ ] Screen mode has keep-awake/display-friendly behavior
- [ ] Screen mode is harder to accidentally disrupt
- [ ] Viewer experience feels distinct from Remote mode
- [ ] Remote mode remains clean and unaffected
- [ ] Any maintenance/escape path is intentional and minimal
- [ ] Build notes were appended to `00_CONTROL_PROMPT.md`

When complete:
- update `00_CONTROL_PROMPT.md`
- mark Phase 4 complete there
- append detailed build notes using the required format
