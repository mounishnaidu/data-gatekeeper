# Data Gatekeeper

Decide whether a dataset is fit to analyze — *before* it is. The upstream step to the [Funnel Auditor](https://github.com/mounishnaidu/funnel-auditor): dirty data in, diagnosed and cleaned data out, with a human approving every change.

Built by **Mounish Naidu** with **Shadow**.

## The idea

Auto-cleaning agents silently corrupt data: they impute what shouldn't be imputed and "fix" structure that is actually correct. This one is built the other way around:

- **Diagnosis is read-only.** The profiler never changes a byte.
- **Dirt vs. structure.** A column missing for ~every lost MQL lives on the won side of the join — that's structure, not dirt. The gatekeeper proves which is which (P(missing | lost) ≈ 1) instead of guessing. No fix is ever proposed for structural missingness.
- **Every fix costs an approval.** Each proposed change shows what it does, how many rows it touches, and how to undo it. Deny by default.
- **Quarantine, not deletion.** Rows that can't be trusted (orphan join keys, impossible dates) move to `quarantine.csv` with their reason — deletion destroys evidence.
- **Originals are never modified.** Cleaned copies, a quarantine file, and a full `cleaning_log.json` land in `clean/`.

## Prerequisites

- Python 3.10 or higher
- pandas 2.0 or higher

## Installation

```bash
git clone https://github.com/mounishnaidu/data-gatekeeper
cd data-gatekeeper
pip install -r requirements.txt
```

## Quick start

```bash
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
| Non-negative values | negatives where they can't be real (quantities, prices) |

Single-table datasets work too: set `join: null` and the join-dependent checks are skipped, with missingness reported without a structural verdict — a human decides.

## The demo: manufactured dirt, honest grading

Real demo data is too clean to prove anything, so `make_messy.py` injects 9 kinds of realistic dirt into the Olist funnel data — dupes, casing variants, bad date formats, padded keys, orphan deals, impossible dates — with a seeded RNG. Every injection is recorded in `demo_data/manifest.json`: the gatekeeper is graded against that ground truth.

On the current demo data it catches everything in the manifest:

- 50 + 5 duplicate rows, 20 padded keys, 3 orphan deals
- 118 + 10 miscapitalized categories → normalized to canonical spelling
- 30 wrong-format dates → re-parsed; 10 unparseable → blanked, rows kept
- 4 impossible date orders → quarantined for human review
- 8 structural-missingness columns correctly identified as *structure* and left alone

It also surfaced pre-existing dirt in the "clean" source data: ~60 blank origins and 1 impossible date the original audit never noticed.

## Proven on real data

- **Online Retail (541,909 transactions):** 5,268 duplicate rows; 26 Description spellings inconsistent across 632 rows; 10,624 negative quantities; 2 negative prices; all InvoiceDates non-ISO; 1,454 missing Descriptions; 135,080 missing CustomerIDs (24.9%) — correctly left for human decision, since a naive cleaner would drop a quarter of the rows.
- **Online course enrollments (23,918 rows):** 8 issues, all benign sparsity (missing ratings, reviews, ages) — verdict: fit to analyze.

## The pipeline

```
make_messy.py → demo_data/ (dirty)
    → gatekeeper profile → issues + evidence
    → gatekeeper clean (approved fixes) → clean/ (mqls_clean.csv, deals_clean.csv, quarantine.csv, cleaning_log.json)
    → funnel auditor → audit findings + report
```

`auditor_config.json` points the funnel auditor at the cleaned output — the two tools compose.

## Project structure

```
gatekeeper/
  profiler.py   # read-only diagnosis -> issues with evidence
  fixes.py      # approved fixes, applied in dependency order, fully logged
  gates.py      # human approval gates — nothing mutates without a yes
cli.py                # profile | clean
demo_config.json      # two-table demo (Olist, join on mql_id)
retail_config.json    # single-table demo (Online Retail, join: null)
course_config.json    # single-table demo (course enrollments, join: null)
make_messy.py         # manufacture the dirty demo data (seeded)
demo_data/            # dirty CSVs + manifest.json (ground truth)
auditor_config.json   # funnel-auditor config pointed at clean/
clean/                # cleaned output (generated)
```

## Technologies used — and why

- **Python** — readable, runs anywhere, no server to deploy. Same reason as the auditor: a data-quality tool that needs infrastructure doesn't get run before the analysis, which is the only time it matters.
- **pandas** — the checks are dataframe operations: `duplicated()` for dupes, string ops for padding and casing, merge indicators for orphans, `to_datetime` with strict vs flexible parsing for dates. No custom engine needed.
- **JSON configs** — tables, join keys, date columns, category columns, and encodings all live in the config. A new dataset is a new config, including single-table mode (`join: null`) and per-table encodings.
- **CSV + JSON outputs** — cleaned data stays in CSV (the format it arrived in, so nothing is lost in translation); the cleaning log is JSON (machine-readable audit trail). Quarantine is a CSV with a reason column, so a human can review every excluded row.
- **CLI, no web server** — the gatekeeper runs before analysis, on the analyst's machine, on the actual files. No upload step, no service — which also means the data never leaves the machine it started on.
