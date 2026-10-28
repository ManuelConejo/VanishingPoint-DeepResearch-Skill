# Example run: cs-ai, one question, unedited output

What the skill wrote for one question, kept as produced (v0.5.1 with `--fulltext`, 2026-10-28). Nothing was edited by hand; `REPORT.html`, `PASSAGES.md`, `studies.csv` and `references.*` were regenerated
offline with `tools/export_report.py`, `tools/passages.py` and `tools/export_data.py`.

| File | What it is |
|---|---|
| `QUESTION.md` | the question and the date T |
| `REPORT.md` / `REPORT.html` | the eight-section report; the HTML shows, under each reference, the exact source passage behind each checked claim |
| `card.json`, `result.json` | machine annex (claims checked, studies and criteria) |
| `verdicts.json`, `PASSAGES.md` | downstream verification: 32 claims, 26 FOUND, 3 DISTORTED, 3 ABSENT (`REPORT.md`, Methodology Appendix; the 3 ABSENT claims were removed from the card, so `verdicts.json` keeps 29); 29/29 passages located |
| `run.json` | gateway calls counted from the journal: 50 (44 by the searchers, 6 by the verifier); `result.json` says `calls_used: 44` because the run did not add the verifier's 6 calls as SKILL.md section 7 asks (kept as produced) |
| `scope.md`, `searches/` | framing and the searchers' notes with gateway receipts |
| `studies.csv`, `references.bib/.ris/.json` | exports for spreadsheets and reference managers |

Not included: `sources/` (full texts of third-party papers, their licences are not ours) and `state/` (gateway journal and cache).
Because `sources/` is not shipped, re-running `tools/finish_run.py` or `tools/export_report.py` on this folder rebuilds
`PASSAGES.md` at 0/29 and an HTML report without the source passages: the files shipped here are the ones built before `sources/`
was removed.

Read it with its limits: one run (n = 1); 50 gateway calls (`run.json`); the verifier re-read 12 whole arXiv sources and reported
a model cost of about 9.1 USD (`verdicts.json`, `cost_usd`), because this run used the optional full-text verification
(`--fulltext`), off by default. The cost of the research itself is not recorded in these files. This is one case, not
a benchmark.
