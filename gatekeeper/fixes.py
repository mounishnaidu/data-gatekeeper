"""Apply human-approved fixes. Every mutation is logged; originals are never
touched. Anything removed goes to quarantine with its reason — deletion is
not a cleaning strategy.
"""
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

ORDER = ["strip_keys", "normalize_categories", "fix_dates",
         "drop_duplicates", "quarantine_orphans",
         "quarantine_impossible_dates"]


def _log():
    return {"started": datetime.now().isoformat(), "actions": []}


def _record(log, key, title, before, after, detail=""):
    log["actions"].append({
        "fix": key, "title": title,
        "rows_before": int(before), "rows_after": int(after),
        "rows_changed": int(before - after) if key != "normalize_categories"
        and key != "strip_keys" and key != "fix_dates" else detail,
        "detail": detail,
    })


def apply_fixes(tables, config, approved_keys) -> tuple[dict, dict, pd.DataFrame]:
    """Returns (cleaned_tables, log, quarantine_df)."""
    log = _log()
    key = config["join"]["key"]
    tables = {n: df.copy() for n, df in tables.items()}
    quarantine_parts = []

    def qreason(df, reason):
        d = df.copy()
        d["_quarantine_reason"] = reason
        return d

    if "strip_keys" in approved_keys:
        n = 0
        for name, df in tables.items():
            s = df[key].fillna("")
            mask = s != s.str.strip()
            n += int(mask.sum())
            df.loc[mask, key] = s.str.strip()
        _record(log, "strip_keys", "Strip whitespace on join keys",
                sum(map(len, tables.values())), sum(map(len, tables.values())),
                f"{n} keys stripped")

    if "normalize_categories" in approved_keys:
        total = 0
        for name, df in tables.items():
            for col in config.get("categorical_cols", []):
                if col not in df.columns:
                    continue
                s = df[col].fillna("")
                norm = s.str.strip().str.lower()
                canon = (s[norm != ""].groupby(norm).agg(
                    lambda x: x.mode().iloc[0]) if (norm != "").any()
                    else pd.Series(dtype=str))
                mask = (norm != "") & (s != norm.map(canon))
                total += int(mask.sum())
                df.loc[mask, col] = norm[mask].map(canon)
        _record(log, "normalize_categories", "Normalize category spellings",
                sum(map(len, tables.values())), sum(map(len, tables.values())),
                f"{total} values normalized to canonical spelling")

    if "fix_dates" in approved_keys:
        bad_total = 0
        normalized_total = 0
        # NOTE: no reset_index() anywhere in here — the boolean masks below
        # are built on df's original index and must stay aligned with it.
        for name, spec in config["tables"].items():
            df = tables[name]
            for col in spec.get("date_cols", []):
                if col not in df.columns:
                    continue
                s = df[col].fillna("")
                parsed = pd.to_datetime(s, format="mixed", errors="coerce")
                bad = (s != "") & parsed.isna()
                n_bad = int(bad.sum())
                bad_total += n_bad
                if n_bad:
                    # Blank the date, keep the row: a bad date doesn't
                    # invalidate the MQL/deal, and removing the row would
                    # orphan its join partner downstream.
                    df.loc[bad, col] = ""
                fmt = spec.get("datetime_formats", {}).get(col, "%Y-%m-%d")
                good = (s != "") & parsed.notna()
                normalized_total += int(good.sum())
                df.loc[good, col] = parsed[good].dt.strftime(fmt)
            tables[name] = df
        _record(log, "fix_dates", "Re-parse dates; blank the unparseable",
                sum(map(len, tables.values())), sum(map(len, tables.values())),
                f"{bad_total} unparseable dates blanked (rows kept); "
                f"{normalized_total} dates normalized to ISO")

    if "drop_duplicates" in approved_keys:
        dropped = 0
        for name, df in tables.items():
            before = len(df)
            tables[name] = df.drop_duplicates().reset_index(drop=True)
            dropped += before - len(tables[name])
        _record(log, "drop_duplicates", "Drop exact duplicate rows",
                sum(map(len, tables.values())) + dropped,
                sum(map(len, tables.values())),
                f"{dropped} duplicate rows dropped")

    if "quarantine_orphans" in approved_keys:
        left, right = tables[config["join"]["left"]], tables[config["join"]["right"]]
        l_keys = set(left[key].fillna("").str.strip())
        mask = ~right[key].fillna("").str.strip().isin(l_keys)
        n = int(mask.sum())
        if n:
            quarantine_parts.append(qreason(right[mask], "orphan join key"))
            tables[config["join"]["right"]] = right[~mask].reset_index(drop=True)
        _record(log, "quarantine_orphans", "Quarantine orphan deals",
                len(right) + 0, len(tables[config["join"]["right"]]),
                f"{n} orphan rows quarantined (not deleted)")

    if "quarantine_impossible_dates" in approved_keys:
        lspec, rspec = (config["tables"][config["join"]["left"]],
                        config["tables"][config["join"]["right"]])
        lc, rc = lspec["date_cols"][0], rspec["date_cols"][0]
        left = tables[config["join"]["left"]][[key, lc]]
        right = tables[config["join"]["right"]]
        m = left.merge(right[[key, rc]], on=key, how="inner")
        bad_ids = set(m[pd.to_datetime(m[rc], format="mixed", errors="coerce")
                        < pd.to_datetime(m[lc], format="mixed",
                                         errors="coerce")][key])
        mask = right[key].isin(bad_ids)
        n = int(mask.sum())
        if n:
            quarantine_parts.append(
                qreason(right[mask], "won_date before first_contact_date"))
            tables[config["join"]["right"]] = right[~mask].reset_index(drop=True)
        _record(log, "quarantine_impossible_dates",
                "Quarantine impossible date order",
                len(right), len(tables[config["join"]["right"]]),
                f"{n} rows quarantined (not deleted)")

    quarantine = (pd.concat(quarantine_parts, ignore_index=True)
                  if quarantine_parts else pd.DataFrame())
    log["finished"] = datetime.now().isoformat()
    log["final_rows"] = {n: len(df) for n, df in tables.items()}
    log["quarantined_rows"] = len(quarantine)
    return tables, log, quarantine


def write_outputs(tables, log, quarantine, out_dir="clean") -> Path:
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        # restore empty strings to true blanks for CSV honesty
        df.to_csv(d / f"{name}_clean.csv", index=False)
    if len(quarantine):
        quarantine.to_csv(d / "quarantine.csv", index=False)
    (d / "cleaning_log.json").write_text(json.dumps(log, indent=2))
    return d
