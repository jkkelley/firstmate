# Intake questionnaire

Ask in order. Batch three to five at a time. Q1 branches the rest — get it first.

If a repo path is available, read it and pre-fill answers, then ask the user to
confirm or correct rather than asking cold.

---

## Block A — scope (ask first, alone)

**Q1. What are we wireframing?**

- `frontend` — user-facing screens
- `backend` — service, data flow, or API shape (produces a FigJam diagram, not screens)
- `fullstack` — screens plus the service diagram behind them
- `infra` — cluster / cloud architecture diagram from manifests or Terraform
- `design-system` — component inventory or audit of an existing library

**Q2. Deliverable?** `screens` | `flow` | `both`
Backend and infra scopes are forced to `flow` by the validator.

**Q3. Is there existing source material?**
Repo path, OpenAPI spec, k8s manifests, PRD, running localhost URL, or nothing.
A running localhost URL means `generate_figma_design` can capture the real UI
instead of wireframing from scratch — always ask before drawing something that
already exists.

---

## Block B — target

**Q4. New Figma file or an existing one?** If existing, the file URL. If new,
which team or org plan key (from `whoami`).

**Q5. Is this a standalone exploration or part of an existing product?**
Standalone means generic primitives are fine. Part of a product means the
existing design system is mandatory and reuse is enforced.

**Q6. Design system?** Library name, or `none`.

---

## Block C — form factor

**Q7. Breakpoints?** Any of `desktop` (1440x1024), `tablet` (834x1194),
`mobile` (390x844). Multiple allowed; each multiplies the frame count.

**Q8. Fidelity?**

- `skeleton` — boxes and labels only, structure argument
- `lofi` — grayscale, real copy, real data shapes
- `midfi` — design system components, real tokens

**Q9. Density?** `dense` (ops dashboards, tables, admin) or `comfortable`
(marketing, onboarding, consumer). Drives padding and row height.

**Q10. Navigation pattern?** `sidebar` | `topnav` | `tabs` | `none`

---

## Block D — content

**Q11. List the screens.** For each: name, purpose in one line, the data it
displays, and the single primary action.

**Q12. Who is the primary user and what are their top three jobs?**

**Q13. Auth model?** `none` | `authenticated` | `rbac`
`rbac` forces a `permission-denied` state on every screen.

**Q14. Which states must every screen carry?**
Default is `default`, `empty`, `loading`, `error`. Add `success`,
`permission-denied`, `offline` as needed. Cutting states here is the most common
way a wireframe set turns out useless in review.

---

## Block E — guardrails

**Q15. Who reviews this?** `eng` | `design` | `stakeholder`

**Q16. Non-goals?** What is explicitly out of scope for this pass.

**Q17. Done when?** One sentence the user would accept as completion.

**Q18. Layer naming prefix?** Default `wf`.

---

## Brief schema

Write answers to `wireframe-brief.json`:

```json
{
  "project": "prospector",
  "scope": "frontend",
  "artifact": "both",
  "source": { "repo": "<path-to-repo>", "localhost_url": null, "spec": null },
  "target": { "mode": "new", "file_url": null, "plan_key": "1234567890" },
  "standalone": false,
  "design_system": { "use": true, "library": "Prospector UI" },
  "breakpoints": ["desktop", "mobile"],
  "fidelity": "lofi",
  "density": "dense",
  "nav_pattern": "sidebar",
  "auth_model": "rbac",
  "states": ["default", "empty", "loading", "error", "permission-denied"],
  "screens": [
    {
      "name": "Business Search",
      "purpose": "Find businesses by geography and category",
      "data": "paginated business list, filter facets, result count",
      "primary_action": "Save business to a list"
    }
  ],
  "flow": [
    {
      "from": "Business Search",
      "to": "Business Detail",
      "trigger": "click result row"
    }
  ],
  "primary_user": "sales rep prospecting a new territory",
  "user_jobs": ["find businesses in a ZIP", "qualify them", "export a list"],
  "audience": "eng",
  "non_goals": ["visual design", "mobile web"],
  "done_when": "Every screen has all five states and an eng can estimate from it",
  "naming_prefix": "wf"
}
```

Optional keys may be omitted. `validate_brief.py` reports exactly what is
missing or inconsistent — run it rather than eyeballing the JSON.
