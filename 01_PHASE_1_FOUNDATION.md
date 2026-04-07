# Phase 1 Prompt — Android Shell Foundation

Work only on Phase 1.

Before doing anything:
- read `00_CONTROL_PROMPT.md`
- obey all constraints in that file
- do not work on future phases except for minimal structural preparation if absolutely necessary

## Objective

Create the Android shell foundation for the LYRN mobile app.

This phase establishes the base native app structure and the fullscreen WebView container that will host the LYRN frontend.

## Scope

Build the following:

- Android project structure for the LYRN app
- a main activity or equivalent app entry structure
- a fullscreen WebView-based shell
- required WebView settings for a modern web app
- clean layout/container setup for immersive use
- a simple startup flow that can later branch into role selection
- project organization that cleanly separates:
  - native shell logic
  - config/state handling
  - WebView host behavior
  - future role-based launch behavior

## Requirements

- The WebView must support the LYRN frontend properly
- Enable the expected modern WebView capabilities such as:
  - JavaScript
  - DOM storage
  - any other sane settings required for a modern dashboard
- The app should feel fullscreen and intentional
- Avoid browser-like chrome and unnecessary native clutter
- Structure the code so future phases can inject config and role behavior without hacks
- Keep implementation simple and readable

## Do Not Do Yet

- no first-run role selector UI yet unless absolutely needed as a placeholder
- no real config injection behavior yet
- no Screen mode restrictions yet
- no kiosk or lock behavior yet
- no settings screen beyond bare minimum scaffolding
- no speculative extra features

## Deliverable Standard

At the end of Phase 1, the project should have a clean Android shell capable of loading a WebView-based LYRN frontend container in a way that is ready for role/config expansion.

## Completion Checklist

Only mark this phase complete when all are true:

- [ ] Android shell foundation exists
- [ ] Fullscreen WebView host is implemented
- [ ] WebView settings are configured appropriately
- [ ] Code structure is clean and extensible for upcoming phases
- [ ] No backend-specific assumptions were introduced
- [ ] Build notes were appended to `00_CONTROL_PROMPT.md`

When complete:
- update `00_CONTROL_PROMPT.md`
- mark Phase 1 complete there
- append detailed build notes using the required format
