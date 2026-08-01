# Build rules

Read before the first `use_figma` call. These are non-negotiable; violating them
is what makes wireframes unusable in review.

## Structure

- Every container uses **auto layout** with explicit padding and item spacing.
  Absolute positioning only for genuinely overlaid elements (modals, toasts,
  dropdowns, tooltips).
- One screen state per top-level frame. Never stack states inside one frame.
- Frames are placed at the exact x/y from `build-plan.json`. Do not improvise
  positions — the grid is what makes reruns comparable.
- Constraints set so frames survive resizing. A wireframe that breaks when
  someone drags an edge will be ignored.

## Naming

Semantic, slash-delimited, lowercase:

```
wf/business-search/default        top-level frame
nav/sidebar                       navigation region
region/filters                    layout region
card/metric                       repeated block
table/row                         repeated row
state/empty-message               state-specific content
```

Never ship `Frame 42`, `Rectangle 7`, `Group 12`. Rename as you create.

## Density tokens

| token | dense | comfortable |
|---|---|---|
| page padding | 24 | 48 |
| section gap | 16 | 32 |
| card padding | 12 | 24 |
| table row height | 36 | 56 |
| control height | 32 | 44 |

## Fidelity

- **skeleton** — gray boxes plus a text label naming what goes there. No icons,
  no real copy.
- **lofi** — grayscale only. Real labels, plausible data, real empty-state copy.
  Single neutral ramp: `#FFFFFF #F5F5F5 #E5E5E5 #A3A3A3 #525252 #171717`.
- **midfi** — instance real library components, bind real variables. Every color
  is a variable reference, never a raw hex.

Color enters a wireframe only as a semantic variable from the design system.
A wireframe styled with loose hex codes produces code with loose hex codes.

## Content

- Plausible placeholder data, never lorem ipsum. A business directory shows
  business names; a metrics view shows numbers with realistic magnitude and
  units.
- Empty states carry the actual recovery action, not "No data".
- Error states name the failure class: not-found, forbidden, timeout, validation.
- Loading states show the skeleton shape of the content that is coming, not a
  centered spinner.
- Longest-plausible-string test: at least one row or label must be long enough
  to expose truncation and wrapping decisions.

## Reuse

1. `search_design_system` for the component before creating anything.
2. `get_libraries` if you are unsure which libraries the file subscribes to.
3. Instance, do not copy. A detached duplicate of a library component is a defect.
4. Only create a new component when the search genuinely returned nothing, and
   record why in the CREATED section of the handoff.

## Annotation

Each frame gets a title layer above it: screen name, state, breakpoint. Each
screen gets a one-line intent note. For `audience: stakeholder`, add a short
caption per frame explaining what the user is doing there; for `audience: eng`,
annotate data sources and interaction states instead.

## Safety

- Never delete or restructure layers you did not create in this session without
  explicit confirmation.
- Build into a new page inside an existing file rather than the page someone is
  actively working on.
- If `use_figma` fails partway through a frame, delete the partial frame before
  retrying. Half-built frames stacked on retries are the main source of canvas
  garbage.
