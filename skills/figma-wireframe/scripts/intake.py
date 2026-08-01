#!/usr/bin/env python3
"""Interactive wireframe intake. Writes a brief the validator will accept.

Run it yourself when you want to fill the brief without a back-and-forth in
chat; otherwise the agent asks the same questions in conversation.

Usage: intake.py [--out wireframe-brief.json]
"""

import argparse
import json
import sys

DIAGRAM_ONLY = {"backend", "infra"}


def ask(prompt, default=None, required=True):
    suffix = f" [{default}]" if default is not None else ""
    while True:
        try:
            val = input(f"{prompt}{suffix}: ").strip()
        except EOFError:
            print("\naborted", file=sys.stderr)
            sys.exit(1)
        if not val and default is not None:
            return default
        if val:
            return val
        if not required:
            return ""
        print("  required")


def choose(prompt, options, default=None):
    print(f"\n{prompt}")
    for i, opt in enumerate(options, 1):
        mark = " (default)" if opt == default else ""
        print(f"  {i}. {opt}{mark}")
    while True:
        raw = input("  > ").strip()
        if not raw and default:
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        if raw in options:
            return raw
        print("  pick a number or an exact option name")


def multi(prompt, options, default=None):
    default = default or []
    print(f"\n{prompt} (comma-separated numbers)")
    for i, opt in enumerate(options, 1):
        mark = " *" if opt in default else ""
        print(f"  {i}. {opt}{mark}")
    while True:
        raw = input("  > ").strip()
        if not raw and default:
            return list(default)
        picks = [p.strip() for p in raw.split(",") if p.strip()]
        out = []
        ok = True
        for p in picks:
            if p.isdigit() and 1 <= int(p) <= len(options):
                out.append(options[int(p) - 1])
            elif p in options:
                out.append(p)
            else:
                ok = False
                break
        if ok and out:
            return list(dict.fromkeys(out))
        print("  pick comma-separated numbers")


def yesno(prompt, default=True):
    d = "Y/n" if default else "y/N"
    raw = input(f"{prompt} [{d}]: ").strip().lower()
    if not raw:
        return default
    return raw.startswith("y")


def collect_list(label):
    print(f"\n{label} (blank line to finish)")
    out = []
    while True:
        v = input("  - ").strip()
        if not v:
            return out
        out.append(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="wireframe-brief.json")
    args = ap.parse_args()

    print("=" * 62)
    print(" Figma wireframe intake")
    print(" Answers become wireframe-brief.json — the reproducibility contract.")
    print("=" * 62)

    brief = {}
    brief["project"] = ask("\nProject name")

    # Block A
    scope = choose("What are we wireframing?",
                   ["frontend", "backend", "fullstack", "infra", "design-system"],
                   default="frontend")
    brief["scope"] = scope

    if scope in DIAGRAM_ONLY:
        artifact = "flow"
        print(f"\n  -> scope '{scope}' produces a diagram; artifact set to 'flow'")
    elif scope == "design-system":
        artifact = "screens"
        print("\n  -> design-system inventory; artifact set to 'screens'")
    else:
        artifact = choose("Deliverable?", ["screens", "flow", "both"],
                          default="both")
    brief["artifact"] = artifact

    brief["source"] = {
        "repo": ask("\nRepo path (blank if none)", default="", required=False) or None,
        "localhost_url": ask("Running localhost URL (blank if none)",
                             default="", required=False) or None,
        "spec": ask("OpenAPI / manifest / PRD path (blank if none)",
                    default="", required=False) or None,
    }
    if brief["source"]["localhost_url"]:
        print("  -> note: generate_figma_design can capture this UI directly "
              "instead of wireframing it from scratch")

    # Block B
    mode = choose("New Figma file or existing?", ["new", "existing"], default="new")
    target = {"mode": mode, "file_url": None, "plan_key": None}
    if mode == "new":
        target["plan_key"] = ask("Plan key (from the whoami tool)")
    else:
        target["file_url"] = ask("Figma file URL")
    brief["target"] = target

    brief["standalone"] = yesno("\nStandalone exploration (not part of an "
                                "existing product)?", default=False)
    use_ds = yesno("Use an existing design system library?",
                   default=not brief["standalone"])
    brief["design_system"] = {
        "use": use_ds,
        "library": ask("  Library name") if use_ds else None,
    }

    needs_screens = artifact in {"screens", "both"}

    if needs_screens:
        brief["breakpoints"] = multi("Breakpoints?",
                                     ["desktop", "tablet", "mobile"],
                                     default=["desktop"])
        brief["fidelity"] = choose("Fidelity?", ["skeleton", "lofi", "midfi"],
                                   default="lofi")
        if brief["fidelity"] == "midfi" and not use_ds:
            print("  -> midfi needs a design system; dropping to lofi")
            brief["fidelity"] = "lofi"
        brief["density"] = choose("Density?", ["dense", "comfortable"],
                                  default="comfortable")
        brief["nav_pattern"] = choose("Navigation pattern?",
                                      ["sidebar", "topnav", "tabs", "none"],
                                      default="sidebar")
        brief["auth_model"] = choose("Auth model?",
                                     ["none", "authenticated", "rbac"],
                                     default="authenticated")

        states = multi("States every screen must carry?",
                       ["default", "empty", "loading", "error", "success",
                        "permission-denied", "offline"],
                       default=["default", "empty", "loading", "error"])
        if brief["auth_model"] == "rbac" and "permission-denied" not in states:
            states.append("permission-denied")
            print("  -> rbac: added 'permission-denied'")
        brief["states"] = states

        print("\nScreens. Blank name to finish.")
        screens = []
        while True:
            name = input("\n  Screen name: ").strip()
            if not name:
                break
            screens.append({
                "name": name,
                "purpose": ask("    Purpose (one line)"),
                "data": ask("    Data displayed"),
                "primary_action": ask("    Single primary action"),
            })
        brief["screens"] = screens
    else:
        brief["fidelity"] = "lofi"
        brief["screens"] = []

    if artifact in {"flow", "both"}:
        print("\nFlow edges. Blank 'from' to finish.")
        flow = []
        while True:
            src = input("\n  From: ").strip()
            if not src:
                break
            flow.append({
                "from": src,
                "to": ask("    To"),
                "trigger": ask("    Trigger"),
            })
        brief["flow"] = flow

    brief["primary_user"] = ask("\nPrimary user (one line)")
    brief["user_jobs"] = collect_list("Their top jobs")
    brief["audience"] = choose("Who reviews this?",
                               ["eng", "design", "stakeholder"], default="eng")
    brief["non_goals"] = collect_list("Non-goals / out of scope")
    brief["done_when"] = ask("\nDone when (one sentence)")
    brief["naming_prefix"] = ask("Layer naming prefix", default="wf")

    with open(args.out, "w") as fh:
        json.dump(brief, fh, indent=2)
        fh.write("\n")

    n_screens = len(brief.get("screens") or [])
    n_states = len(brief.get("states") or [])
    n_bps = len(brief.get("breakpoints") or [])
    print(f"\nwrote {args.out}")
    if n_screens:
        print(f"  {n_screens} screens x {n_states} states x {n_bps} breakpoints "
              f"= {n_screens * n_states * n_bps} frames")
    print(f"\nNext:\n  python3 scripts/validate_brief.py {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
