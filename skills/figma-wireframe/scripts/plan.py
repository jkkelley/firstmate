#!/usr/bin/env python3
"""Turn a validated wireframe brief into a deterministic build plan.

Same brief in, same frame names and canvas coordinates out. The agent must not
compute layout itself — that is what makes two runs comparable.

Usage:
  plan.py wireframe-brief.json --out build-plan.json [--markdown plan.md]
  plan.py wireframe-brief.json --out build-plan.json --diff build-plan.prev.json
"""

import argparse
import json
import re
import sys

BREAKPOINTS = {
    "desktop": {"width": 1440, "height": 1024},
    "tablet": {"width": 834, "height": 1194},
    "mobile": {"width": 390, "height": 844},
}

# state -> column order. Anything unlisted sorts last, alphabetically.
STATE_ORDER = [
    "default", "empty", "loading", "error",
    "success", "permission-denied", "offline",
]

DENSITY_TOKENS = {
    "dense": {
        "page_padding": 24, "section_gap": 16, "card_padding": 12,
        "row_height": 36, "control_height": 32,
    },
    "comfortable": {
        "page_padding": 48, "section_gap": 32, "card_padding": 24,
        "row_height": 56, "control_height": 44,
    },
}

NAV_REGIONS = {
    "sidebar": ["nav/sidebar", "region/header", "region/content"],
    "topnav": ["nav/top", "region/content"],
    "tabs": ["nav/top", "nav/tabs", "region/content"],
    "none": ["region/content"],
}

STATE_CONTENT = {
    "default": "populated content at realistic volume; include one "
               "longest-plausible-string row to expose truncation",
    "empty": "empty illustration block, one-line explanation, and the primary "
             "recovery action as a real button",
    "loading": "skeleton blocks matching the shape of the default content; no "
               "centered spinner",
    "error": "named failure class (not-found / timeout / validation), what the "
             "user can do next, retry affordance",
    "success": "confirmation of the primary action plus the obvious next step",
    "permission-denied": "role-aware message naming the missing permission and "
                         "who to ask",
    "offline": "cached-content notice and queued-action indicator",
}

FRAME_GAP = 160          # gap between frames on canvas
LABEL_OFFSET = 64        # vertical room above each frame for its title layer
BREAKPOINT_BAND_GAP = 400  # vertical gap between breakpoint bands


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", str(text).strip().lower())
    return s.strip("-") or "untitled"


def sort_states(states):
    def key(s):
        return (STATE_ORDER.index(s) if s in STATE_ORDER else len(STATE_ORDER), s)
    return sorted(states, key=key)


def build_frames(brief):
    prefix = brief.get("naming_prefix") or "wf"
    screens = brief.get("screens") or []
    artifact = brief.get("artifact")
    if artifact == "flow":
        return []

    states = sort_states(brief.get("states") or ["default"])
    breakpoints = [b for b in (brief.get("breakpoints") or ["desktop"])
                   if b in BREAKPOINTS]
    nav = brief.get("nav_pattern") or "none"
    density = brief.get("density") or "comfortable"
    tokens = DENSITY_TOKENS[density]

    frames = []
    band_y = 0

    for bp in breakpoints:
        dims = BREAKPOINTS[bp]
        col_step = dims["width"] + FRAME_GAP
        row_step = dims["height"] + FRAME_GAP + LABEL_OFFSET

        for row, screen in enumerate(screens):
            name = screen.get("name", f"screen-{row + 1}")
            for col, state in enumerate(states):
                frames.append({
                    "id": f"{prefix}/{slug(name)}/{slug(state)}/{bp}",
                    "name": f"{prefix}/{slug(name)}/{slug(state)}",
                    "screen": name,
                    "state": state,
                    "breakpoint": bp,
                    "x": col * col_step,
                    "y": band_y + row * row_step,
                    "width": dims["width"],
                    "height": dims["height"],
                    "regions": NAV_REGIONS.get(nav, NAV_REGIONS["none"]),
                    "purpose": screen.get("purpose", ""),
                    "data": screen.get("data", ""),
                    "primary_action": screen.get("primary_action", ""),
                    "state_content": STATE_CONTENT.get(
                        state, "state-specific content"),
                    "title_layer": f"{name} — {state} — {bp}",
                })

        rows = max(len(screens), 1)
        band_y += rows * row_step + BREAKPOINT_BAND_GAP

    return frames


def build_mermaid(brief):
    flow = brief.get("flow") or []
    if not flow:
        return None
    lines = ["flowchart LR"]
    nodes = {}
    for screen in brief.get("screens") or []:
        n = screen.get("name")
        if n:
            nodes[n.strip().lower()] = slug(n)
    for edge in flow:
        for endpoint in ("from", "to"):
            v = (edge.get(endpoint) or "").strip()
            if v and v.lower() not in nodes:
                nodes[v.lower()] = slug(v)
    for label, node_id in sorted(nodes.items(), key=lambda kv: kv[1]):
        lines.append(f'    {node_id}["{label.title()}"]')
    for edge in flow:
        src = nodes.get((edge.get("from") or "").strip().lower())
        dst = nodes.get((edge.get("to") or "").strip().lower())
        if src and dst:
            trigger = str(edge.get("trigger", "")).replace('"', "'")
            lines.append(f'    {src} -->|"{trigger}"| {dst}')
    return "\n".join(lines)


def build_plan(brief):
    frames = build_frames(brief)
    density = brief.get("density") or "comfortable"
    plan = {
        "project": brief.get("project"),
        "scope": brief.get("scope"),
        "artifact": brief.get("artifact"),
        "fidelity": brief.get("fidelity"),
        "density": density,
        "tokens": DENSITY_TOKENS[density],
        "design_system": brief.get("design_system") or {"use": False},
        "target": brief.get("target") or {},
        "frame_count": len(frames),
        "frames": frames,
        "mermaid": build_mermaid(brief),
        "build_order": [f["id"] for f in frames],
        "done_when": brief.get("done_when"),
        "non_goals": brief.get("non_goals") or [],
    }
    return plan


def to_markdown(plan):
    out = []
    a = out.append
    a(f"# Build plan — {plan['project']}")
    a("")
    a(f"scope `{plan['scope']}` · artifact `{plan['artifact']}` · "
      f"fidelity `{plan['fidelity']}` · density `{plan['density']}`")
    ds = plan["design_system"]
    a(f"design system: {ds.get('library') if ds.get('use') else 'none (generic primitives)'}")
    a("")
    a(f"**{plan['frame_count']} frames** to build, in this order.")
    a("")
    if plan["frames"]:
        a("| # | frame | breakpoint | x | y | size |")
        a("|---|---|---|---|---|---|")
        for i, f in enumerate(plan["frames"], 1):
            a(f"| {i} | `{f['name']}` | {f['breakpoint']} | {f['x']} | {f['y']} "
              f"| {f['width']}x{f['height']} |")
        a("")
        a("## Per-state content requirement")
        a("")
        seen = []
        for f in plan["frames"]:
            if f["state"] not in seen:
                seen.append(f["state"])
                a(f"- **{f['state']}** — {f['state_content']}")
        a("")
        a("## Regions per frame")
        a("")
        a(", ".join(f"`{r}`" for r in plan["frames"][0]["regions"]))
        a("")
        a("## Density tokens")
        a("")
        for k, v in plan["tokens"].items():
            a(f"- {k}: {v}")
        a("")
    if plan["mermaid"]:
        a("## Flow diagram (feed to generate_diagram)")
        a("")
        a("```mermaid")
        a(plan["mermaid"])
        a("```")
        a("")
    if plan["non_goals"]:
        a("## Out of scope")
        a("")
        for n in plan["non_goals"]:
            a(f"- {n}")
        a("")
    a("## Done when")
    a("")
    a(plan.get("done_when") or "_not specified_")
    return "\n".join(out)


def diff_plans(new, old):
    new_map = {f["id"]: f for f in new.get("frames", [])}
    old_map = {f["id"]: f for f in old.get("frames", [])}
    added = sorted(set(new_map) - set(old_map))
    removed = sorted(set(old_map) - set(new_map))
    moved = sorted(
        fid for fid in set(new_map) & set(old_map)
        if (new_map[fid]["x"], new_map[fid]["y"],
            new_map[fid]["width"], new_map[fid]["height"]) !=
           (old_map[fid]["x"], old_map[fid]["y"],
            old_map[fid]["width"], old_map[fid]["height"])
    )
    unchanged = len(set(new_map) & set(old_map)) - len(moved)
    return {"added": added, "removed": removed, "moved": moved,
            "unchanged": unchanged}


def main():
    ap = argparse.ArgumentParser(description="Brief -> deterministic build plan.")
    ap.add_argument("brief")
    ap.add_argument("--out", default="build-plan.json")
    ap.add_argument("--markdown", help="also write a human-readable plan")
    ap.add_argument("--diff", help="previous build-plan.json to compare against")
    args = ap.parse_args()

    try:
        with open(args.brief) as fh:
            brief = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL  cannot read {args.brief}: {exc}", file=sys.stderr)
        return 1

    plan = build_plan(brief)

    with open(args.out, "w") as fh:
        json.dump(plan, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"wrote {args.out}  ({plan['frame_count']} frames)")

    if args.markdown:
        with open(args.markdown, "w") as fh:
            fh.write(to_markdown(plan) + "\n")
        print(f"wrote {args.markdown}")

    if args.diff:
        try:
            with open(args.diff) as fh:
                old = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"FAIL  cannot read {args.diff}: {exc}", file=sys.stderr)
            return 1
        d = diff_plans(plan, old)
        print("\nDIFF vs previous plan")
        print(f"  unchanged: {d['unchanged']}")
        for label in ("added", "removed", "moved"):
            print(f"  {label}: {len(d[label])}")
            for fid in d[label]:
                print(f"    {fid}")
        print("\nOnly touch the frames listed above. Leave unchanged frames alone.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
