# Data Gatekeeper

Decide whether a dataset is fit to analyze — *before* it is. The upstream step to the [Funnel Auditor](https://github.com/mounishnaidu/funnel-auditor): dirty data in, diagnosed and cleaned data out, with a human approving every change.

Built by **Mounish Naidu** with **Shadow**.

## The idea

Auto-cleaning agents silently corrupt data: they impute what shouldn't be imputed and "fix" structure that is actually correct. This one is built the other way around:

- **Diagnosis is read-only.** The profiler never changes a byte.
- **Dirt vs. structure.** Sometimes a column is empty for a reason — for example, lost deals never got a closing date, so that column is empty for every lost deal. That's structure, not dirt. The gatekeeper proves which is which by checking: is this column empty for basically every lost deal? If yes, it's structure, and no fix is proposed for it.
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
| Exact duplicates | duplicate rows — they inflate every count |
| Join-key padding | extra spaces in the ID that links two tables — these silently break the link |
| Orphan keys | records in one table pointing to IDs that don't exist in the other |
| Category consistency | one channel written in many spellings (`paid_search` vs `Paid_Search`) |
| Date parsing | dates written in different formats, and entries that aren't dates at all |
| Impossible date order | a deal marked won before the customer was first contacted |
| Missingness | empty by design (left alone) vs genuinely missing data |
| Non-negative values | negative numbers where they can't be real (quantities, prices) |

Single-table datasets work too: if your data is one table instead of two linked tables, set `join: null`. The link-related checks are skipped, and empty columns are reported without a verdict — a human decides.

## The demo: manufactured dirt, honest grading

Real demo data is too clean to prove anything, so `make_messy.py` injects 9 kinds of realistic dirt into the Olist funnel data — dupes, casing variants, bad date formats, padded keys, orphan deals, impossible dates — with a fixed random seed, so the same dirt is generated every time. Every injection is recorded in `demo_data/manifest.json`: the gatekeeper is graded against that known answer key.

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
demo_data/            # dirty CSVs + manifest.json (known answer key)
auditor_config.json   # funnel-auditor config pointed at clean/
clean/                # cleaned output (generated)
```

## Technologies used — and why

- **Python** — the programming language the tool is written in. It runs on any computer, with no server to set up. Same reason as the auditor: a data-quality tool that needs infrastructure doesn't get run before the analysis, which is the only time it matters.
- **pandas** — a Python tool for working with tables of data. The checks are table operations: finding duplicate rows, spotting extra spaces and spelling differences, finding IDs with no match, and reading dates in different formats. No custom engine needed.
- **JSON configs** — plain-text settings files. Which tables to check, which columns are dates, which are categories, and how the files are encoded all live in the settings file. A new dataset means a new settings file.
- **CSV + JSON outputs** — cleaned data stays as CSV (the same spreadsheet-style format it arrived in, so nothing is lost); the cleaning log is JSON (a structured record a program can read). Quarantined rows go in a CSV with a column explaining why each was excluded, so a human can review every one.
- **Command-line tool, no web server** — you run it by typing a command, on your own machine, on your own files. No upload step, no service — which also means your data never leaves the machine it started on.
