"""Data Gatekeeper CLI.

    python3 cli.py profile --config demo_config.json
    python3 cli.py clean --config demo_config.json            # asks per fix
    python3 cli.py clean --config demo_config.json --yes      # auto-approve

Diagnosis is always free and read-only. Cleaning writes only cleaned copies
plus a quarantine file and a log — the originals are never modified.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gatekeeper import fixes, profiler
from gatekeeper.fixes import ORDER
from gatekeeper.gates import ProposedFix, request_approval


def show(issues, show_work):
    for i in issues:
        badge = {"critical": "🔴", "warning": "🟡", "info": "🟢"}[i.severity]
        print(f"{badge} {i.title}\n   {i.summary}")
        if show_work:
            print(f"   [evidence] {i.evidence}")
            print(f"   [check]    {i.how_checked}")
            if i.proposed_fix:
                print(f"   [fix]      {i.proposed_fix}")
        print()


def main() -> int:
    ap = argparse.ArgumentParser(description="Data quality gatekeeper.")
    ap.add_argument("command", choices=["profile", "clean"])
    ap.add_argument("--config", required=True)
    ap.add_argument("--show-work", action="store_true")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    config_path = Path(args.config)
    config = json.loads(config_path.read_text())
    # resolve relative data paths against the config file's directory
    for spec in config["tables"].values():
        p = Path(spec["path"])
        if not p.is_absolute():
            spec["path"] = str(config_path.parent / p)

    print(f"Gatekeeping: {config['name']}")
    issues, tables = profiler.profile(config)
    print(f"Diagnosed {len(issues)} issues.\n")
    show(issues, args.show_work)

    if args.command == "profile":
        print("Profile only — nothing was changed.")
        return 0

    # clean: propose each fix with a human gate
    fixable = [i for i in issues if i.proposed_fix_key]

    def affected(i):
        e = i.evidence
        for k in ("affected_rows", "duplicate_rows", "padded_keys",
                  "orphan_deals", "impossible_rows"):
            if k in e:
                return int(e[k])
        return int(e.get("wrong_format", 0) + e.get("unparseable", 0))

    approved = []
    for issue in sorted(fixable,
                        key=lambda i: ORDER.index(i.proposed_fix_key)
                        if i.proposed_fix_key in ORDER else 99):
        fix = ProposedFix(
            key=issue.proposed_fix_key,
            title=issue.title,
            description=issue.proposed_fix,
            reversible=("Re-run from the originals; originals untouched. "
                        "Quarantined rows recoverable from quarantine.csv."),
            affected_rows=affected(issue),
        )
        if request_approval(fix, auto_approve=args.yes):
            approved.append(issue.proposed_fix_key)

    if not approved:
        print("\nNo fixes approved — nothing was written.")
        return 0

    cleaned, log, quarantine = fixes.apply_fixes(tables, config, approved)
    out = fixes.write_outputs(cleaned, log, quarantine,
                              out_dir=str(config_path.parent / "clean"))
    print(f"\nWrote cleaned tables + quarantine + log to: {out}/")
    print(f"Final rows: {log['final_rows']} | "
          f"quarantined: {log['quarantined_rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
