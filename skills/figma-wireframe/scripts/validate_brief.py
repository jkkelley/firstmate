#!/usr/bin/env python3
"""Validate a wireframe brief. Exit 0 = proceed, 1 = fix the brief.

Stdlib only. Usage: validate_brief.py wireframe-brief.json [--json]
"""

import argparse
import json
import sys

SCOPES = {"frontend", "backend", "fullstack", "infra", "design-system"}
ARTIFACTS = {"screens", "flow", "both"}
FIDELITY = {"skeleton", "lofi", "midfi"}
DENSITY = {"dense", "comfortable"}
NAV = {"sidebar", "topnav", "tabs", "none"}
AUTH = {"none", "authenticated", "rbac"}
AUDIENCE = {"eng", "design", "stakeholder"}
BREAKPOINTS = {"desktop", "tablet", "mobile"}
KNOWN_STATES = {
    "default", "empty", "loading", "error",
    "success", "permission-denied", "offline",
}
DIAGRAM_ONLY_SCOPES = {"backend", "infra"}

REQUIRED = ["project", "scope", "artifact", "fidelity", "audience", "done_when"]


def err(errors, msg):
    errors.append(msg)


def enum_check(errors, brief, key, allowed, required=True):
    val = brief.get(key)
    if val is None:
        if required:
            err(errors, f"{key}: missing (expected one of {sorted(allowed)})")
        return
    if val not in allowed:
        err(errors, f"{key}: {val!r} is not one of {sorted(allowed)}")


def validate(brief):
    errors, warnings = [], []

    if not isinstance(brief, dict):
        return ["brief must be a JSON object"], []

    for key in REQUIRED:
        if not brief.get(key):
            err(errors, f"{key}: required and must be non-empty")

    enum_check(errors, brief, "scope", SCOPES)
    enum_check(errors, brief, "artifact", ARTIFACTS)
    enum_check(errors, brief, "fidelity", FIDELITY)
    enum_check(errors, brief, "audience", AUDIENCE)
    enum_check(errors, brief, "density", DENSITY, required=False)
    enum_check(errors, brief, "nav_pattern", NAV, required=False)
    enum_check(errors, brief, "auth_model", AUTH, required=False)

    scope = brief.get("scope")
    artifact = brief.get("artifact")
    screens = brief.get("screens") or []
    states = brief.get("states") or []
    breakpoints = brief.get("breakpoints") or []
    ds = brief.get("design_system") or {}
    target = brief.get("target") or {}

    # --- target -------------------------------------------------------
    mode = target.get("mode")
    if mode not in {"new", "existing"}:
        err(errors, "target.mode: must be 'new' or 'existing'")
    elif mode == "new" and not target.get("plan_key"):
        err(errors, "target.plan_key: required when target.mode is 'new' "
                    "(get it from the whoami tool)")
    elif mode == "existing" and not target.get("file_url"):
        err(errors, "target.file_url: required when target.mode is 'existing'")

    # --- scope / artifact coherence -----------------------------------
    if scope in DIAGRAM_ONLY_SCOPES and artifact != "flow":
        err(errors, f"artifact: scope '{scope}' produces a diagram, so artifact "
                    f"must be 'flow' (got {artifact!r})")
    if scope == "design-system" and artifact != "screens":
        err(errors, "artifact: scope 'design-system' must use artifact 'screens' "
                    "(an inventory board of component frames)")

    needs_screens = artifact in {"screens", "both"}

    # --- screens ------------------------------------------------------
    if needs_screens and not screens:
        err(errors, "screens: at least one screen required for this artifact type")
    if not needs_screens and screens:
        warnings.append("screens: listed but artifact is 'flow'; they will be "
                        "used as diagram nodes only")

    seen = set()
    for i, s in enumerate(screens):
        where = f"screens[{i}]"
        if not isinstance(s, dict):
            err(errors, f"{where}: must be an object")
            continue
        name = s.get("name")
        if not name:
            err(errors, f"{where}.name: required")
            continue
        key = name.strip().lower()
        if key in seen:
            err(errors, f"{where}.name: duplicate screen name {name!r}")
        seen.add(key)
        for field in ("purpose", "data", "primary_action"):
            if not s.get(field):
                err(errors, f"{where}.{field}: required for {name!r} — ask the "
                            f"user, do not invent it")

    # --- states -------------------------------------------------------
    if needs_screens:
        if not states:
            err(errors, "states: required — minimum ['default','empty','loading','error']")
        else:
            unknown = [s for s in states if s not in KNOWN_STATES]
            if unknown:
                err(errors, f"states: unknown {unknown}; allowed {sorted(KNOWN_STATES)}")
            if "default" not in states:
                err(errors, "states: must include 'default'")
            for expected in ("empty", "loading", "error"):
                if expected not in states:
                    warnings.append(f"states: '{expected}' omitted — reviews "
                                    f"usually stall without it")
        if brief.get("auth_model") == "rbac" and "permission-denied" not in states:
            err(errors, "states: auth_model 'rbac' requires a 'permission-denied' state")

    # --- form factor --------------------------------------------------
    if needs_screens:
        if not breakpoints:
            err(errors, "breakpoints: required — at least one of "
                        f"{sorted(BREAKPOINTS)}")
        else:
            bad = [b for b in breakpoints if b not in BREAKPOINTS]
            if bad:
                err(errors, f"breakpoints: unknown {bad}")
        if not brief.get("density"):
            err(errors, "density: required for screen output ('dense' or 'comfortable')")
        if not brief.get("nav_pattern"):
            err(errors, "nav_pattern: required for screen output")

    # --- fidelity / design system -------------------------------------
    if brief.get("fidelity") == "midfi" and not ds.get("use"):
        err(errors, "design_system.use: fidelity 'midfi' requires a design system; "
                    "drop to 'lofi' or name a library")
    if ds.get("use") and not ds.get("library"):
        err(errors, "design_system.library: required when design_system.use is true")
    if brief.get("standalone") is False and not ds.get("use"):
        warnings.append("design_system: brief says this is part of an existing "
                        "product but no library is set — reuse cannot be enforced")

    # --- flow ---------------------------------------------------------
    flow = brief.get("flow") or []
    if artifact in {"flow", "both"} and not flow:
        err(errors, "flow: required when artifact is 'flow' or 'both'")
    names = {s.get("name", "").strip().lower() for s in screens if isinstance(s, dict)}
    for i, edge in enumerate(flow):
        if not isinstance(edge, dict):
            err(errors, f"flow[{i}]: must be an object")
            continue
        for field in ("from", "to", "trigger"):
            if not edge.get(field):
                err(errors, f"flow[{i}].{field}: required")
        if screens:
            for field in ("from", "to"):
                v = (edge.get(field) or "").strip().lower()
                if v and v not in names:
                    warnings.append(f"flow[{i}].{field}: {edge.get(field)!r} is "
                                    f"not a listed screen")

    # --- scale sanity -------------------------------------------------
    if needs_screens and screens and states and breakpoints:
        total = len(screens) * len(states) * len(breakpoints)
        if total > 60:
            err(errors, f"scale: {total} frames planned "
                        f"({len(screens)} screens x {len(states)} states x "
                        f"{len(breakpoints)} breakpoints). Split this into "
                        f"multiple passes — over ~60 frames the build degrades.")
        elif total > 30:
            warnings.append(f"scale: {total} frames is a long build; consider "
                            f"splitting by breakpoint")

    if not brief.get("non_goals"):
        warnings.append("non_goals: empty — scope creep is likely")

    return errors, warnings


def main():
    ap = argparse.ArgumentParser(description="Validate a wireframe brief.")
    ap.add_argument("brief", help="path to wireframe-brief.json")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    try:
        with open(args.brief) as fh:
            brief = json.load(fh)
    except FileNotFoundError:
        print(f"FAIL  no such file: {args.brief}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"FAIL  {args.brief} is not valid JSON: {exc}", file=sys.stderr)
        return 1

    errors, warnings = validate(brief)

    if args.json:
        print(json.dumps({"ok": not errors, "errors": errors,
                          "warnings": warnings}, indent=2))
        return 1 if errors else 0

    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"FAIL  {e}", file=sys.stderr)

    if errors:
        print(f"\n{len(errors)} error(s). Fix the brief and rerun; "
              f"do not start building.", file=sys.stderr)
        return 1

    print(f"\nOK    brief valid ({len(warnings)} warning(s)). Proceed to plan.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
