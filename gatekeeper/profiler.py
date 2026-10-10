"""Read-only diagnosis. The profiler loads the tables, joins them the way the
funnel auditor will, and reports every data-quality issue it can prove —
each with evidence and the exact check behind it. It changes nothing.
"""
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class Issue:
    title: str
    severity: str            # "info" | "warning" | "critical"
    summary: str
    evidence: dict = field(default_factory=dict)
    how_checked: str = ""
    proposed_fix_key: str = ""   # "" means: no safe automatic fix, human call
    proposed_fix: str = ""


def _load_tables(config):
    tables = {}
    for name, spec in config["tables"].items():
        tables[name] = pd.read_csv(spec["path"], dtype=str).fillna("")
        # keep a raw copy for byte-level checks; work on stripped-later copies
    return tables


def check_duplicates(tables) -> list[Issue]:
    out = []
    for name, df in tables.items():
        n = int(df.duplicated().sum())
        if n:
            out.append(Issue(
                title=f"Duplicate rows in {name}",
                severity="warning",
                summary=(f"{n:,} of {len(df):,} rows in {name} are exact "
                         f"duplicates. They inflate every count built on "
                         f"this table."),
                evidence={"table": name, "duplicate_rows": n,
                          "total_rows": len(df)},
                how_checked="pandas duplicated() over all columns",
                proposed_fix_key="drop_duplicates",
                proposed_fix=(f"Drop exact duplicate rows in {name}, "
                              f"keeping the first occurrence."),
            ))
    return out


def check_missingness(tables, join) -> list[Issue]:
    """Missing values, split into dirt vs structure.

    The structural signature: a column missing for ~every lost MQL
    (P(missing | won==0) ~= 1) lives on the won side of the join — e.g. deal
    attributes that only exist for won deals. That is structure, not dirt:
    no fix is proposed. Anything else is genuine dirt.
    """
    left = tables[join["left"]].copy()
    right = tables[join["right"]].copy()
    key = join["key"]
    merged = left.merge(right, on=key, how="left", indicator=True,
                        suffixes=("", "_deal"))
    # _merge is categorical (from indicator=True) — fill the rest
    merged = merged.fillna(
        {c: "" for c in merged.columns if c != "_merge"})
    merged["won"] = (merged["_merge"] == "both").astype(int)
    out = []
    for col in merged.columns:
        if col in (key, "_merge", "won"):
            continue
        missing = merged[col] == ""
        n_missing = int(missing.sum())
        if not n_missing:
            continue
        lost = merged["won"] == 0
        # structural iff ~every lost MQL is missing this column
        p_miss_given_lost = missing[lost].mean() if lost.any() else 0.0
        n_won_missing = int((missing & (merged["won"] == 1)).sum())
        col_origin = "deals" if col in right.columns else "mqls"
        if p_miss_given_lost >= 0.999:
            out.append(Issue(
                title=f"Structural missingness: {col}",
                severity="info",
                summary=(f"{n_missing:,} missing values in {col}, but "
                         f"{p_miss_given_lost:.0%} of lost MQLs are missing "
                         f"it — this attribute only exists on the won side "
                         f"of the join. Structure, not dirt. Left alone. "
                         f"({n_won_missing:,} won deals also missing it — "
                         f"sparse attribute, noted, not 'fixed'.)"),
                evidence={"column": col, "missing": n_missing,
                          "p_missing_given_lost":
                          round(float(p_miss_given_lost), 4),
                          "won_deals_missing": n_won_missing},
                how_checked=("P(missing | won==0) after the join; >=0.999 "
                             "= lives on the won side = structural"),
            ))
        else:
            out.append(Issue(
                title=f"Missing values: {col} ({col_origin})",
                severity="warning",
                summary=(f"{n_missing:,} missing values in {col} that are "
                         f"NOT explained by the funnel structure — genuine "
                         f"dirt. Left for a human decision."),
                evidence={"column": col, "missing": n_missing,
                          "p_missing_given_lost":
                          round(float(p_miss_given_lost), 4)},
                how_checked="same structural test; failed => dirt",
            ))
    return out


def check_categories(tables, cat_cols) -> list[Issue]:
    out = []
    for name, df in tables.items():
        for col in cat_cols:
            if col not in df.columns:
                continue
            s = df[col].fillna("")
            norm = s.str.strip().str.lower()
            groups = {}
            for raw, n_ in zip(s, norm):
                groups.setdefault(n_, set()).add(raw)
            messy = {k: v for k, v in groups.items() if len(v) > 1 and k != ""}
            if messy:
                # canonical spelling = most frequent raw value per group;
                # only rows NOT already canonical count as affected
                canon = {k: s[norm == k].mode().iloc[0] for k in messy}
                expected = norm.map(canon)
                n_rows = int(((norm.isin(messy)) & (s != expected)).sum())
                detail = {k: sorted(v) for k, v in
                          list(messy.items())[:5]}
                out.append(Issue(
                    title=f"Inconsistent categories: {name}.{col}",
                    severity="warning",
                    summary=(f"{len(messy)} categories in {col} appear in "
                             f"multiple spellings ({n_rows:,} rows affected) "
                             f"— e.g. 'paid_search' vs 'Paid_Search'. Splits "
                             f"one channel into several in every breakdown."),
                    evidence={"table": name, "column": col,
                              "messy_groups": len(messy),
                              "affected_rows": n_rows,
                              "examples": detail},
                    how_checked=("grouped raw values by lower(strip(value)); "
                                 "groups with >1 distinct raw spelling "
                                 "= inconsistent"),
                    proposed_fix_key="normalize_categories",
                    proposed_fix=(f"Normalize {col} to the most frequent "
                                  f"spelling per group (canonical form)."),
                ))
    return out


def check_dates(tables, config) -> list[Issue]:
    out = []
    for name, spec in config["tables"].items():
        df = tables[name]
        for col in spec.get("date_cols", []):
            if col not in df.columns:
                continue
            s = df[col].fillna("")
            nonblank = s != ""
            # strict: expected ISO shapes (date or datetime)
            strict = (pd.to_datetime(s, format="%Y-%m-%d", errors="coerce")
                      .fillna(pd.to_datetime(s, format="%Y-%m-%d %H:%M:%S",
                                             errors="coerce")))
            strict_ok = strict.notna().sum()
            # flexible: pandas 2.x needs format="mixed" for mixed shapes
            flex = pd.to_datetime(s, format="mixed", errors="coerce")
            flex_ok = flex.notna().sum()
            salvageable = int(flex_ok - strict_ok)
            hopeless = int(nonblank.sum() - flex_ok)
            if salvageable or hopeless:
                out.append(Issue(
                    title=f"Date parsing: {name}.{col}",
                    severity="warning" if hopeless else "info",
                    summary=(f"{salvageable:,} dates in {col} parse only "
                             f"with flexible parsing (wrong format, e.g. "
                             f"MM/DD/YYYY); {hopeless:,} are unparseable "
                             f"garbage."),
                    evidence={"table": name, "column": col,
                              "wrong_format": salvageable,
                              "unparseable": hopeless},
                    how_checked=("strict parse as %Y-%m-%d / %Y-%m-%d "
                                 "%H:%M:%S vs flexible parse "
                                 "(format='mixed'); the gap = wrong format, "
                                 "the remainder (non-blank) = garbage"),
                    proposed_fix_key="fix_dates",
                    proposed_fix=(f"Re-parse {col} flexibly into ISO; blank "
                                  f"the unparseable dates but keep the rows "
                                  f"— a bad date doesn't invalidate the MQL."),
                ))
    return out


def check_keys(tables, join) -> list[Issue]:
    out = []
    key = join["key"]
    left, right = tables[join["left"]], tables[join["right"]]

    for name, df in ((join["left"], left), (join["right"], right)):
        padded = df[key].fillna("")
        n_pad = int((padded != padded.str.strip()).sum())
        if n_pad:
            out.append(Issue(
                title=f"Padded join keys in {name}",
                severity="warning",
                summary=(f"{n_pad:,} {key} values in {name} have leading/ "
                         f"trailing whitespace — they will silently fail an "
                         f"exact join and look like missing data."),
                evidence={"table": name, "padded_keys": n_pad},
                how_checked=f"count of {key} where value != value.strip()",
                proposed_fix_key="strip_keys",
                proposed_fix=f"Strip whitespace on {key} in both tables.",
            ))

    # orphan check runs on stripped keys (padding is fixed first)
    l_keys = set(left[key].fillna("").str.strip())
    r_keys = right[key].fillna("").str.strip()
    orphans = int((~r_keys.isin(l_keys)).sum())
    if orphans:
        out.append(Issue(
            title="Orphan join keys in deals",
            severity="critical",
            summary=(f"{orphans} deal rows point at MQLs that don't exist. "
                     f"They can never join — keeping them silently drops "
                     f"them from the funnel; deleting them destroys evidence."),
            evidence={"orphan_deals": orphans},
            how_checked=(f"deals.{key} (stripped) not in set(mqls.{key} "
                         f"(stripped))"),
            proposed_fix_key="quarantine_orphans",
            proposed_fix=("Move orphan deals to a quarantine file for human "
                          "review instead of deleting them."),
        ))
    return out


def check_date_order(tables, join, config) -> list[Issue]:
    left_spec = config["tables"][join["left"]]
    right_spec = config["tables"][join["right"]]
    lc, rc = left_spec["date_cols"][0], right_spec["date_cols"][0]
    key = join["key"]
    left = tables[join["left"]][[key, lc]].copy()
    right = tables[join["right"]][[key, rc]].copy()
    left[key] = left[key].str.strip()
    right[key] = right[key].str.strip()
    m = left.merge(right, on=key, how="inner")
    m[lc] = pd.to_datetime(m[lc], format="mixed", errors="coerce")
    m[rc] = pd.to_datetime(m[rc], format="mixed", errors="coerce")
    bad = m[m[rc] < m[lc]]
    if len(bad):
        out_issue = Issue(
            title="Impossible date order",
            severity="critical",
            summary=(f"{len(bad)} won deals have {rc} earlier than "
                     f"{lc} — negative time-to-close. Corrupt source data, "
                     f"not a business finding."),
            evidence={"impossible_rows": len(bad),
                      "worst_days": int((m[rc] - m[lc]).dt.days.min())},
            how_checked=(f"inner join on stripped {key}; rows where "
                         f"{rc} < {lc}"),
            proposed_fix_key="quarantine_impossible_dates",
            proposed_fix=("Move these rows to quarantine for human review — "
                          "no automatic correction; any 'fix' would be a "
                          "guess."),
        )
        return [out_issue]
    return []


def profile(config) -> tuple[list[Issue], dict]:
    """Run every check. Returns (issues, tables). Read-only."""
    tables = _load_tables(config)
    issues: list[Issue] = []
    issues += check_duplicates(tables)
    issues += check_keys(tables, config["join"])
    issues += check_categories(tables, config.get("categorical_cols", []))
    issues += check_dates(tables, config)
    issues += check_missingness(tables, config["join"])
    issues += check_date_order(tables, config["join"], config)
    order = {"critical": 0, "warning": 1, "info": 2}
    return sorted(issues, key=lambda i: order[i.severity]), tables
