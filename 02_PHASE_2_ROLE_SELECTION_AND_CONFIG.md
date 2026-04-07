# Phase 2 Prompt — First-Run Role Selection and Config Model

Work only on Phase 2.

Before doing anything:
- read `00_CONTROL_PROMPT.md`
- read the Phase 1 build notes in that file
- do not erase prior notes
- keep scope limited to this phase

## Objective

Add the first-run setup flow and the app configuration model.

This phase defines how the app stores and uses role-based startup behavior without changing the core connection model.

## Scope

Build the following:

- first-run onboarding or setup flow
- role selection with exactly two roles:
  - Remote
  - Screen
- persistent storage for selected role
- persistent storage for connection-related app settings
- a clean native config model that the app can use consistently
- startup decision logic so the app knows what role it is in on future launches
- ability to edit or reset role/config later if reasonable within the current architecture

## Required App Config Concepts

The app should have a clear internal config/state model for at least:

- app role
- target URL or equivalent connection target
- token or auth value if applicable
- startup route or startup behavior
- keep-awake preference for Screen mode if needed
- any minimal flags needed to support clean launch behavior

You may refine names, but keep the model simple and practical.

## UI Expectations

- first-run flow should be clean and minimal
- role selection should be obvious
- Screen mode should be described as a viewer/display style role
- Remote mode should be described as the full interactive role
- do not overwhelm the user with technical language

## Do Not Do Yet

- no advanced viewer lock behavior yet
- no hidden gesture unlocks yet
- no kiosk-hardening yet
- no full route locking yet
- no heavy native settings panel unless needed minimally
- no speculative enterprise settings system

## Deliverable Standard

At the end of Phase 2, the app should know what role it is, remember it, and have a clean config model ready to be injected into the web layer later.

## Completion Checklist

Only mark this phase complete when all are true:

- [ ] First-run role selection exists
- [ ] Remote and Screen roles are clearly implemented
- [ ] Role selection persists across launches
- [ ] Config model exists and is stored cleanly
- [ ] Startup logic uses saved role/config state
- [ ] Architecture remains simple and frontend-focused
- [ ] Build notes were appended to `00_CONTROL_PROMPT.md`

When complete:
- update `00_CONTROL_PROMPT.md`
- mark Phase 2 complete there
- append detailed build notes using the required format
