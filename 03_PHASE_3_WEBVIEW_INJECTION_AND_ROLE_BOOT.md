# Phase 3 Prompt — WebView Config Injection and Role-Based Boot Behavior

Work only on Phase 3.

Before doing anything:
- read `00_CONTROL_PROMPT.md`
- read all prior build notes in that file
- stay within this phase unless a tiny support change is unavoidable

## Objective

Connect the native app state to the web layer cleanly.

This phase makes the Android shell actually drive the LYRN frontend by injecting the needed config/state into the WebView before or during load in a reliable way.

## Scope

Build the following:

- config injection from native app state into the WebView
- clean startup behavior based on app role
- role-aware route or launch handling
- page reload/update behavior when config changes
- any minimal abstraction needed so injected values remain centralized and predictable

## Expected Behavior

The web layer should be able to determine, from app-provided values:

- whether the app is in Remote mode or Screen mode
- what target it should connect to
- any auth/token value required
- what startup route or startup behavior it should use
- any viewer/display flags required for Screen mode behavior

Use the cleanest mechanism appropriate for this stack. Favor simple and reliable injection over cleverness.

## Screen Role Expectations

Screen mode should start in a display-oriented way rather than feeling like the full interactive app.

That may include:
- booting directly to a specific route
- applying viewer flags
- hiding unnecessary controls if appropriate from the current architecture
- simplifying the startup experience

Keep it practical and avoid overengineering.

## Do Not Do Yet

- no full kiosk escape restrictions yet
- no gesture unlock systems yet
- no aggressive native lock task features yet unless absolutely necessary
- no speculative remote management extras

## Deliverable Standard

At the end of Phase 3, the app should pass role/config cleanly into the frontend and launch appropriately based on Remote vs Screen behavior.

## Completion Checklist

Only mark this phase complete when all are true:

- [ ] Native config is injected into the WebView cleanly
- [ ] Remote role boots into the expected interactive experience
- [ ] Screen role boots into the expected display-oriented experience
- [ ] Config changes can be reflected reliably
- [ ] Injection logic is centralized and maintainable
- [ ] Build notes were appended to `00_CONTROL_PROMPT.md`

When complete:
- update `00_CONTROL_PROMPT.md`
- mark Phase 3 complete there
- append detailed build notes using the required format
