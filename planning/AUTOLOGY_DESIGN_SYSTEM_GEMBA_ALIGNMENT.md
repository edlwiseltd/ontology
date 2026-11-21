# Autology — design system aligned on GEMBA: state and plan

*21 November 2026. Status: **first increment applied.** The owner sent three desktop screenshots of GEMBA in its
dark theme and gave the direction: **not an identical copy; something modern, inspired by it.** So GEMBA supplies the
identity (deep navy, teal, pill navigation, large rounded cards, small spaced labels), and the rest is Autology's
own design. The GEMBA server itself is still unreachable from the engineering environment; its stylesheets were
not seen. The screenshots hold business data and are **not** kept in this repository, which is public.*

## 0. What was done, and what it rests on

| Element | Source | State |
|---|---|---|
| Dark palette: ground `#0a1420`, surfaces `#0a1625` and `#0e1c2d`, lines `#1e2b3d` / `#213144`, text `#e8f0fa` / `#9fb3cc` / `#6d829c`, teal `#13a3ab` and `#5eead4`, alert `#ff6b7d`, amber `#ffc857` | **Measured** on the screenshots, pixel by pixel | Applied |
| Green `#3fe0a1`, violet `#b59cff` | Measured on compressed images: approximate | Applied |
| Segmented tabs with a filled current tab, pills in capitals with wide spacing, large rounded cards, uppercase table headers, small labels above titles | **Seen** on the screenshots | Applied, as shapes; sizes are Autology's (the screenshots were taken at an unknown zoom) |
| Light theme (teal on a cool light ground), gradients, shadows, hover and focus states, motion, status dots | **Autology's own design**, on the same identity | Applied |
| Typeface | Not identifiable from a screenshot | A modern system stack (Inter where installed, Segoe UI Variable on Windows); no font is downloaded |
| Text on the filled teal | GEMBA uses white, which measures 3.1 to 1 | **Deliberately different:** dark text on teal in the dark theme, white on a deeper teal in the light theme, both above 4.5 to 1 |
| Data freshness | GEMBA shows when its snapshot was taken | Applications show "Engine data read at hh:mm" beside Reload |

Guarded by `studio/web/tests/design.test.ts`: both themes define the same roles; text meets 4.5 to 1 on every
ground it is used on; an application's accent is one of six names. Checked: 88 unit tests, 319 browser checks,
no sideways scrolling at phone width.

**Not done yet:** shared React components (tables, cards, badges and timelines are still built in place and share
the look through the stylesheets); the header with a workspace selector; dashboards beyond the overview tiles; a
themed ontology graph; **French and English**; tablet-specific layout. GEMBA's light theme, its phone layout and
its stylesheets were never seen.

## 1. What is needed from GEMBA, and how to get it

| Needed | Why | How |
|---|---|---|
| Screenshots of Graph, Schedule, Wall, Brief, Accounting and Settings, at desktop, tablet and phone widths | Layout, navigation, density, responsive behaviour | The capture tool below |
| The stylesheets | The real tokens: colours, type scale, spacing, radii, shadows | The same tool saves them |
| An inventory of what the pages use | Which colours and sizes are actually used, and how header, navigation, cards, tables, badges and buttons are built | The same tool |
| Menu and tab labels, in French and English if both exist | Navigation structure and the vocabulary of the French interface | The same tool (`navigation-*.json`) |
| Anything the tool cannot see | Hover and focus states, dialogs, empty and error states, the logo and its rules of use | Extra screenshots, or the source styles |

**The capture tool**: `studio/web/tools/capture_reference.mjs`. It runs on a computer that can reach GEMBA. It opens
a browser window, the operator signs in and opens each page, and the tool writes a local folder: screenshots at
three sizes, the stylesheets, and one inventory per page. It sends nothing anywhere.

    cd studio\web
    node tools\capture_reference.mjs http://<gemba address>/ --pages "Graph,Schedule,Wall,Brief,Accounting,Settings" --scramble

`--scramble` replaces every letter and digit on screen before each screenshot, so layout and typography are kept
and business content is not. Images, charts and logos are not altered. The inventory files hold style values and
tag and class names, and no page text; menu and tab labels are kept apart in `navigation-*.json`. **The operator
looks at the folder before sharing it.** Tested on Autology's own Studio and on a test page (text scrambled in the
screenshots; no page text in the inventories).

## 2. Where Autology's interface stands today (verified in the code)

| Aspect | State | Where |
|---|---|---|
| Stack | Next.js 16, React 19, TypeScript; the graph is drawn with `@xyflow/react`. **Kept**: no migration to OWL | `studio/web/package.json` |
| Tokens | A first set exists as CSS custom properties: 13 colours for light and dark, one radius, one gap, one font stack. Font sizes and most spacings are still literal values in the rules | `studio/web/app/globals.css` (210 lines) |
| Runtime styling | Its own sheet with the `rt-` prefix, reusing the page's tokens; an accent chosen from a closed list of six names in the manifest. A manifest never carries a colour or a style | `studio/web/runtime/runtime.css` (60 lines) |
| Components | Views are written directly with class names; there is no shared component library (no common table, card, badge or timeline component) | `studio/web/components/`, `studio/web/runtime/views.tsx` |
| Shell and navigation | Studio: a top bar, a left column of use cases, tabs per use case. Applications: a top bar and a left menu in groups | `Workbench.tsx`, `RuntimeApp.tsx` |
| Theme | Automatic, light, dark | `globals.css` |
| Responsive | Breakpoints at 900 px and 760 px; browser tests check keyboard reach and no sideways scrolling on a phone | `globals.css`, `e2e/` |
| Localization | **None.** English only, written in the components (about 140 strings in the runtime, about 480 in Studio); the page declares `lang="en"` | — |
| Data freshness indicator | **None** | — |
| Separation from the Engine | Presentation decides nothing: every permission, rule and state comes from the Engine's answers. Tested | `studio/web/tests/`, `tests/test_studio_separation.py` |

## 3. Requested components, and what each will be built from

| Requested | Today | To build |
|---|---|---|
| Application shell and navigation | Two different shells (Studio, runtime) | One shell component with slots, used by both |
| Header and workspace selector | A breadcrumb in the top bar; no selector | Header with a workspace selector fed by the platform's list |
| Dashboard and KPI cards | Overview cards in the runtime, built in place | `KpiCard`, `Dashboard` |
| Entity tables and detail panels | Tables and detail views in the runtime, built in place | `DataTable` (paged, sortable where the Engine allows), `DetailPanel` |
| Status indicators and approval cards | Pills for stage and state; the review inbox | `StatusBadge`, `ApprovalCard` |
| Workflow and audit timelines | Ordered lists | `Timeline` |
| Ontology graph presentation | React Flow canvas with its default look | Themed nodes and edges from the tokens |
| Data freshness indicators | None | `Freshness`: when the Engine answered, and a reload action. It shows the Engine's time, never a guess |
| French and English | None | A dictionary per language, a language switch, `lang` set on the page. Labels that come from a model stay as the model wrote them |
| Desktop, tablet, phone | Two breakpoints | Breakpoints and behaviour taken from GEMBA |

All of them are generic: none knows a domain, and the same components draw Studio, the ontology designer, the
architect review, the application designer and every generated application.

## 4. Constraints that hold whatever GEMBA looks like

* React and TypeScript stay. Nothing is migrated to OWL.
* No GEMBA business logic, no Odoo integration code and no domain behaviour is copied. Only the visual language and
  the interaction patterns are followed.
* Components present; the Engine authorises, validates and governs. A component never hides an action as a
  substitute for a refusal by the Engine.
* The Application Builder's manifest stays closed: a design chooses among named options, never a free style.
* Existing behaviour, authorization tests, accessibility checks and CI stay as they are: 85 unit tests and 319
  browser checks must keep passing; test identifiers on elements are kept.

## 5. Plan, once the reference is available

| Step | Content | Evidence |
|---|---|---|
| 1 | Read the capture; write the token table (colour, type, spacing, radius, shadow, breakpoints) with, for each value, the GEMBA file or measurement it comes from | Token table with sources |
| 2 | Tokens in one file; both stylesheets use only tokens | No literal colour or size left outside the token file (a test) |
| 3 | The shared components of §3, each with its states (default, hover, focus, disabled, empty, error) | Unit tests; a page showing every component |
| 4 | Studio, the ontology designer, the architect review and the application designer moved onto the components | Existing browser checks unchanged |
| 5 | The application runtime moved onto the same components | The 108 application checks unchanged |
| 6 | French and English | Every string through the dictionary; a test that no key is missing in either language |
| 7 | Validation | Desktop and phone screenshots beside GEMBA's, page by page, with the differences listed; keyboard and contrast checks |

Step 6 does not depend on the look and can start earlier; its French wording should follow GEMBA's labels where the
two products name the same thing, which is why the labels are part of the capture.

## 6. What will be reported as different, in advance

Some differences are certain and intended: Autology has no Schedule, Wall, Brief or Accounting page of its own,
because its screens are generated from a model; a generated application shows its governance status (simulation,
release, what is not authorised), which GEMBA has no reason to show; and anything GEMBA draws with OWL widgets will
be redrawn with React components, so small differences of rendering are to be expected and will be listed.
