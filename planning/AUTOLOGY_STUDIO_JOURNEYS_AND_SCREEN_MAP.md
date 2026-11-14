# Autology Studio — journeys and screen map

*14 November 2026. Wireframe-level. "Today" means implemented and covered by Studio's browser tests.*

## Screens

```
┌ Header: ◆ Autology Studio │ Workspace › Use case [stage] │ member [admin] · theme · sign out ┐
├ Left navigator ────────────┬ Main ───────────────────────────────────────────────────────────┤
│ Use cases (stage badges)   │ Tabs: Overview │ Model                                          │
│ [New] → template form      │ Overview: stage stepper (Production locked), "Execution now",    │
│ Coming next (labelled)     │   readiness checks, change-stage form (admins), stage history   │
│                            │ Model: entity list │ canvas (graph) │ inspector (attributes,     │
│                            │   relationships); list and canvas share the selection          │
└────────────────────────────┴─────────────────────────────────────────────────────────────────┘
Narrow screens (< 900 px): header, navigator and main stack vertically; the canvas keeps a fixed height and the
list/inspector stay usable (no horizontal page scroll, checked on an iPhone 13 viewport).
```

| Screen | Today | Next |
|---|---|---|
| Sign-in | Token sign-in; refused token and unavailable platform states | Company sign-in (OIDC) with a session pattern (D9 open part) |
| Use-case catalogue | Real stages and stale marker | Search, filters |
| Use-case overview | Stepper, effective execution state, checks, move, history, integrity/stale warnings | Readiness score (REL-3), release history (REL-1) |
| Model | Read-only canvas + list + inspector from the engine | Draft editing, validation anchors, auto-layout (after the licence review of ELK), process/org/agent views |
| AI Architect | Not shown; listed as planned | Conversation + typed proposals, provisional nodes (blocked on ARC-1, D7/D10) |

## Journeys

1. **Open a use case and see what may run** (today): sign in → choose a use case → Overview shows the stage and
   "Execution now" as enforced by the engine.
2. **Move to simulation** (today): Check now → read failing checks → choose Simulation → give a reason → the
   platform re-checks and records the move with the member's name; the history shows it.
3. **Create a use case** (today): New → approved template → identifier and name → it appears in Draft.
4. **Understand the model** (today): Model → select an entity in the list (keyboard) or the graph → the inspector
   shows attributes, states and relationships.
5. **Try to bypass the UI** (today, browser test): a non-admin calls the stage API directly → 403; calls another
   workspace → 404.
6. **Describe → AI proposes → visualise → edit → validate → evidence → simulate → governed release** (target):
   needs the blocked backends listed in the [API matrix](AUTOLOGY_STUDIO_API_CONTRACT_MATRIX.md).

## Accessibility today

Keyboard: every control is a native button, input or select; the entity list is a keyboard alternative to the
canvas with the same selection; focus rings visible. Colour is never the only signal (stage text, ✓/✗ plus
screen-reader text for checks). Text contrast measured in the browser tests: 16.2:1 light, 15.4:1 dark.
Not yet: full canvas keyboard editing (editing does not exist yet), a screen-reader audit, axe automation.
