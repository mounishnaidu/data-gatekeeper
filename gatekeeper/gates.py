"""Approval gates. Same rule as the funnel auditor: nothing is written,
deleted, or moved without an explicit human yes. Diagnosis is free; every
mutation costs an approval.
"""
from dataclasses import dataclass


@dataclass
class ProposedFix:
    key: str           # machine key the applier understands
    title: str
    description: str
    reversible: str
    affected_rows: int


def request_approval(fix: ProposedFix, auto_approve: bool = False) -> bool:
    print(f"\n[FIX] {fix.title}")
    print(f"  What: {description_wrap(fix.description)}")
    print(f"  Rows affected: {fix.affected_rows:,}")
    print(f"  Undo: {fix.reversible}")
    if auto_approve:
        print("  (--yes passed: auto-approved)")
        return True
    answer = input("  Approve? [y/N] ").strip().lower()
    approved = answer in ("y", "yes")
    print(f"  -> {'APPROVED' if approved else 'DENIED — skipped'}")
    return approved


def description_wrap(s: str) -> str:
    return s
