# Data Gatekeeper

Decide whether a dataset is fit to analyze — *before* it is. The upstream step to the [funnel auditor](../funnel-auditor): dirty data in, diagnosed and cleaned data out, with a human approving every change.

Built by **Mounish Naidu** with **Shadow**.

## The idea

Auto-cleaning agents silently corrupt data: they impute what shouldn't be imputed and "fix" structure that is actually correct. This one is built the other way around:

- **Diagnosis is read-only.** The profiler never changes a byte.
- **Dirt vs. structure.** A column missing for ~every lost MQL lives on the won side of the join — that's structure, not dirt. The gatekeeper proves which is which (P(missing | lost) ≈ 1) instead of guessing. No fix is ever proposed for structural missingness.
- **Every fix costs an approval.** Each proposed change shows what it does, how many rows it touches, and how to undo it. Deny by default.
- **Quarantine, not deletion.** Rows that can't be trusted (orphan join keys, impossible dates) move to `quarantine.csv` with their reason — deletion destroys evidence.
- **Originals are never modified.** Cleaned copies, a quarantine file, and a full `cleaning_log.json` land in `clean/`.

## Quick start

```bash
cd ~/workspace/data-gatekeeper
python3 cli.py profile --config demo_config.json            # diagnose only, changes nothing
python3 cli.py clean --config demo_config.json              # propose each fix, you approve
python3 cli.py clean --config demo_config.json --yes        # auto-approve (scripting)
```

## What it checks

| Check | What it proves |
|---|---|
| Exact duplicates | `duplicated()` per table — dupes inflate every count |
| Join-key padding | values ≠ stripped values — silent join failures |
| Orphan keys | deals pointing at MQLs that don't exist |
| Category consistency | one channel in many spellings (`paid_search` vs `Paid_Search`) |
| Date parsing | strict ISO vs flexible parse vs unparseable garbage |
| Impossible date order | won_date before first_contact_date |
| Missingness | structural (join artifact, left alone) vs genuine dirt |

## The demo: manufactured dirt, honest grading

Real demo data is too clean to prove anything, so `make_messy.py` injects 9 kinds of realistic dirt into the Olist funnel data — dupes, casing variants, bad date formats, padded keys, orphan deals, impossible dates — with a seeded RNG. Every injection is recorded in `demo_data/manifest.json`: the gatekeeper is graded against that ground truth.

On the current demo data it catches everything in the manifest:

- 50 + 5 duplicate rows, 20 padded keys, 3 orphan deals
- 118 + 10 miscapitalized categories → normalized to canonical spelling
- 30 wrong-format dates → re-parsed; 10 unparseable → blanked, rows kept
- 4 impossible date orders → quarantined for human review
- 8 structural-missingness columns correctly identified as *structure* and left alone

It also surfaced pre-existing dirt in the "clean" source data: ~60 blank origins and 1 impossible date the original audit never noticed.

## The pipeline

```
make_messy.py → demo_data/ (dirty) 
    → gatekeeper profile → issues + evidence
    → gatekeeper clean (approved fixes) → clean/ (mqls_clean.csv, deals_clean.csv, quarantine.csv, cleaning_log.json)
    → funnel auditor → audit findings + report
```

`auditor_config.json` points the funnel auditor at the cleaned output — the two tools compose.

## Layout

```
gatekeeper/
  profiler.py   # read-only diagnosis -> issues with evidence
  fixes.py      # approved fixes, applied in dependency order, fully logged
  gates.py      # human approval gates — nothing mutates without a yes
cli.py                # profile | clean
demo_config.json      # tables, join key, date + category columns
make_messy.py         # manufacture the dirty demo data (seeded)
demo_data/            # dirty CSVs + manifest.json (ground truth)
auditor_config.json   # funnel-auditor config pointed at clean/
clean/                # cleaned output (generated)
```
