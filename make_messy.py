"""Manufacture a realistically dirty funnel dataset from the clean Olist CSVs.

Every injection is seeded and recorded in `manifest.json` — the gatekeeper is
graded against this ground truth. Nothing here is random in the "unknown"
sense: we know exactly what dirt went in, so we know what a correct diagnosis
looks like.
"""
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
SRC = Path("/home/hatch/workspace/goals/data-skills-learning-from-scratch"
           "/files/ecommerce-growth-audit/data/funnel")
OUT = Path("/home/hatch/workspace/data-gatekeeper/demo_data")
OUT.mkdir(parents=True, exist_ok=True)

rng = np.random.default_rng(SEED)
manifest = {"seed": SEED, "injections": []}


def note(kind, target, count, detail):
    manifest["injections"].append(
        {"kind": kind, "target": target, "count": count, "detail": detail})


# ---------- MQLs ----------
mqls = pd.read_csv(SRC / "olist_marketing_qualified_leads_dataset.csv")
ORIG_N = len(mqls)

# 2. casing / whitespace variants in `origin` (before dupes: pick sources first)
dupe_src = set(rng.choice(ORIG_N, 50, replace=False))
idx = [i for i in rng.choice(ORIG_N, 120, replace=False) if i not in dupe_src]
variants = ["Paid_Search", "PAID_SEARCH", " paid_search", "Unknown",
            "UNKNOWN ", "social ", " Social", "EMAIL", "direct_traffic "]
for i, vi in enumerate(idx):
    mqls.loc[vi, "origin"] = variants[i % len(variants)]
note("category_case_whitespace", "mqls.origin", len(idx),
     f"variants like {variants[:4]}... on {len(idx)} rows")

# 3. bad date formats
idx = [i for i in rng.choice(ORIG_N, 40, replace=False) if i not in dupe_src]
for vi in idx[:30]:
    d = pd.to_datetime(mqls.loc[vi, "first_contact_date"])
    mqls.loc[vi, "first_contact_date"] = d.strftime("%m/%d/%Y")  # US format
for vi in idx[30:]:
    mqls.loc[vi, "first_contact_date"] = "not-a-date"
note("bad_date_format", "mqls.first_contact_date", 30,
     "30 rows rewritten as MM/DD/YYYY instead of YYYY-MM-DD")
note("unparseable_date", "mqls.first_contact_date", 10,
     "10 rows set to the literal string 'not-a-date'")

# 4. whitespace-padded join keys
idx = [i for i in rng.choice(ORIG_N, 20, replace=False) if i not in dupe_src]
for vi in idx:
    mqls.loc[vi, "mql_id"] = " " + str(mqls.loc[vi, "mql_id"]) + " "
note("padded_join_key", "mqls.mql_id", len(idx),
     f"{len(idx)} mql_ids wrapped in spaces — will fail an exact join")

# 1. exact duplicate rows — LAST, so no later edit breaks them
dupes = mqls.iloc[sorted(dupe_src)]
mqls = pd.concat([mqls, dupes], ignore_index=True)
note("exact_duplicate_rows", "mqls", 50,
     "50 rows duplicated verbatim and appended (after all other edits)")

mqls.to_csv(OUT / "mqls_dirty.csv", index=False)

# ---------- Closed deals ----------
deals = pd.read_csv(SRC / "olist_closed_deals_dataset.csv")
D_ORIG_N = len(deals)
d_dupe_src = set(rng.choice(D_ORIG_N, 5, replace=False))

# 6. orphan join keys (deals pointing at MQLs that don't exist)
orphans = deals.sample(3, random_state=SEED + 1).copy()
orphans["mql_id"] = ["orphan_" + str(i) for i in range(3)]
deals = pd.concat([deals, orphans], ignore_index=True)
note("orphan_join_key", "deals.mql_id", 3,
     "3 deals with mql_ids matching no MQL row")

# 7. won_date before first_contact_date (negative days_to_close)
mql_dates = pd.read_csv(
    SRC / "olist_marketing_qualified_leads_dataset.csv",
    usecols=["mql_id", "first_contact_date"],
    parse_dates=["first_contact_date"]).set_index("mql_id")["first_contact_date"]
idx = [i for i in rng.choice(D_ORIG_N, 4, replace=False) if i not in d_dupe_src]
n_hit = 0
hit_ids = []
for vi in idx:
    mid = deals.loc[vi, "mql_id"]
    if mid in mql_dates.index:
        bad = mql_dates[mid] - pd.Timedelta(days=int(rng.integers(1, 30)))
        deals.loc[vi, "won_date"] = bad.strftime("%Y-%m-%d %H:%M:%S")
        n_hit += 1
        hit_ids.append(mid)
note("impossible_date_order", "deals.won_date", n_hit,
     f"{n_hit} injected + 1 pre-existing in source data = "
     f"{n_hit + 1} total won_date-earlier-than-first_contact rows; "
     f"injected mql_ids: {hit_ids}")

# 8. casing variants in a deal-side categorical
idx = [i for i in rng.choice(D_ORIG_N, 10, replace=False) if i not in d_dupe_src]
n_hit = 0
for vi in idx:
    v = deals.loc[vi, "business_segment"]
    if isinstance(v, str) and v != "":
        deals.loc[vi, "business_segment"] = v.upper()
        n_hit += 1
note("category_case_whitespace", "deals.business_segment", n_hit,
     f"{n_hit} business_segment values uppercased")

# 5. duplicate deal rows — LAST, so no later edit breaks them
dups = deals.iloc[sorted(d_dupe_src)]
deals = pd.concat([deals, dups], ignore_index=True)
note("exact_duplicate_rows", "deals", 5,
     "5 deal rows duplicated verbatim and appended (after all other edits)")

deals.to_csv(OUT / "deals_dirty.csv", index=False)

note("pre_existing_dirt", "source data", 0,
     "Source data already contained: ~60 blank origins, 1 won_date < "
     "first_contact_date, and ~779 blank has_company values — the "
     "gatekeeper should surface these as genuine findings, not injections.")
note("injection_interaction", "impossible_date_order x unparseable_date", 1,
     "One injected impossible-date row sits on an MQL whose first_contact "
     "date is 'not-a-date', so date-order can't be evaluated for it — it is "
     "correctly caught only as unparseable. Detectable impossible-date "
     "total: 3 injected + 1 pre-existing = 4.")

(OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
print(f"dirty rows: mqls={len(mqls):,} deals={len(deals):,}")
print(f"manifest: {OUT / 'manifest.json'}")
for inj in manifest["injections"]:
    print(f"  - {inj['kind']} on {inj['target']}: {inj['count']}")
