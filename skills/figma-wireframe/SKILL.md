---
name: figma-wireframe
description: Produce structurally-correct wireframes, screen flows, and architecture diagrams as native Figma layers via the Figma MCP server. Use this skill whenever the user mentions wireframes, mockups, screen layouts, UI sketches, user flows, "design this page", "what should this screen look like", Figma, FigJam, or wants to turn a repo, API, PRD, or set of k8s/Terraform manifests into a visual artifact — even if they never say the word "wireframe". Always run the intake questionnaire first; never start drawing from an unstructured request.
---

<!-- maintainers: this is a public, installer-facing skill. Keep it standalone, with no firstmate paths, tools, or vocabulary. -->

# Figma Wireframe

Turns a vague design request into a deterministic, reproducible set of Figma
frames. The determinism comes from a hard pipeline: **interview -> brief.json ->
validate -> plan -> build**. Same brief in, same frames out, every time.

Never skip straight to `use_figma`. An unstructured request produces
unreproducible output, and the second run will look nothing like the first.

## Requirements

- Figma **remote** MCP server connected (`claude plugin install figma@claude-plugins-official`).
  The desktop server cannot write to canvas.
- A **Full or Dev seat on a paid Figma plan**. View/Collab/Starter seats are
  capped at roughly 6 read tool calls per month and cannot write.
- Python 3.9+ for the bundled scripts. Standard library only, no pip installs.

Verify with `whoami` before anything else. If the seat cannot write, stop and
tell the user rather than burning their read quota.

## Pipeline

### 1. Orient

Call `whoami`. Capture the seat type and the list of plan keys — `create_new_file`
needs a `planKey`. If there is exactly one plan, use it. If several, ask which.

### 2. Interview

Read `references/intake-questions.md` and ask the questions **in the
conversation**, in order, in batches of three to five. Do not ask all twenty at
once and do not ask them one at a time.

Rules for the interview:

- **Scope is question one and it branches everything else.** A backend or infra
  answer means the deliverable is a FigJam diagram via `generate_diagram`, not
  screens. Do not build screens for a backend request.
- If a repo path is supplied, **read it before asking the rest**. Routes,
  components, OpenAPI specs, and k8s manifests answer half the questionnaire
  for free. Propose the answers you derived and ask the user to correct them.
  This is the single biggest lever on output quality.
- Never invent a product requirement. Ask.
- Never accept "make it look good" as fidelity. Force a choice.

### 3. Write the brief

Write the answers to `wireframe-brief.json` in the working directory, following
the shape documented in `references/intake-questions.md`. Show it to the user
and get an explicit yes before continuing. The brief is the contract — it is
what makes a rerun reproducible, and it is what the user edits when they want a
change.

### 4. Validate — hard gate

```bash
python3 scripts/validate_brief.py wireframe-brief.json
```

Exit 0 means proceed. Any non-zero exit means fix the brief and rerun. Do not
build past a failed validation, and do not "work around" a validation error by
editing the script.

### 5. Plan

```bash
python3 scripts/plan.py wireframe-brief.json --out build-plan.json --markdown plan.md
```

This expands screens x states into a fixed frame list, assigns every frame a
deterministic name and an exact canvas x/y, and emits the ordered build
sequence. Show `plan.md` to the user and get approval. Do not compute layout
coordinates yourself — the script owns that so two runs land in the same place.

### 6. Build

Read `references/build-rules.md` before the first `use_figma` call.

Work through `build-plan.json` in order, **one frame at a time**:

1. `use_figma` to construct the frame exactly as planned — name, x, y, width, height.
2. `get_screenshot` on the frame you just created.
3. Compare against the plan. Fix it now if it is wrong. Do not batch fixes to the end.

Before creating any component, call `search_design_system` and reuse what
exists. Creating a duplicate of a library component is a defect.

For `artifact` values of `flow` or `both`, generate the flow map with
`generate_diagram` from the Mermaid in `build-plan.json`.

### 7. Handoff

Report in this format, plain text, no prose padding:

```
BUILT
  <frame name> — <breakpoint> — <node link>

REUSED
  <component> from <library>

CREATED
  <component> — why nothing existing fit

ASSUMPTIONS
  1. <every gap filled without being told>

NEXT
  <single next action, or the question blocking you>
```

Leave `wireframe-brief.json` and `build-plan.json` in the repo. They are the
reproducibility artifact — committing them means the next run is a diff, not a
redraw.

## Rerunning and iterating

When the user wants changes, **edit the brief and rerun the pipeline**. Do not
hand-patch frames. `plan.py --diff` against the previous `build-plan.json`
reports which frames are added, removed, or moved, so only those need touching:

```bash
python3 scripts/plan.py wireframe-brief.json --out build-plan.json --diff build-plan.prev.json
```

## Token discipline

Read tools are rate-limited; write tools are not. Therefore:

- `get_metadata` to navigate an existing file. Never `get_design_context` on a
  whole page — it will flood the context window and degrade the output.
- `get_design_context` only on the specific nodes whose styling you need.
- `get_variable_defs` once per file, not per frame.
- `get_screenshot` per built frame is worth the cost; it is the only way the
  model sees its own mistakes.

## Bundled resources

- `references/intake-questions.md` — the questionnaire and the brief schema. Read at step 2.
- `references/build-rules.md` — layout, naming, and content rules. Read at step 6.
- `scripts/intake.py` — interactive questionnaire for the user to run themselves; writes a valid brief.
- `scripts/validate_brief.py` — schema and consistency gate.
- `scripts/plan.py` — brief to deterministic frame plan, Mermaid flow, and diff.
