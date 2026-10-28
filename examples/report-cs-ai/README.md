# Example run: cs-ai, one question, unedited output

What the skill wrote for one question, kept as produced (v0.5.1 with `--fulltext`, 2026-10-28). Nothing was edited by hand;
`REPORT.html`, `PASSAGES.md`, `studies.csv` and `references.*` were regenerated offline with `tools/export_report.py`,
`tools/passages.py` and `tools/export_data.py`.

| File | What it is |
|---|---|
| `QUESTION.md` | the question and the date T |
| `REPORT.md` / `REPORT.html` | the eight-section report; the HTML shows, under each reference, the exact source passage behind each checked claim |
| `card.json`, `result.json` | machine annex (claims checked, studies and criteria) |
| `verdicts.json`, `PASSAGES.md` | downstream verification: 32 claims, 26 FOUND, 3 DISTORTED, 3 ABSENT (the report says so); 29/29 passages located |
| `scope.md`, `searches/` | framing and the searchers' notes with gateway receipts |
| `studies.csv`, `references.bib/.ris/.json` | exports for spreadsheets and reference managers |

Not included: `sources/` (full texts of third-party papers, their licences are not ours) and `state/` (gateway journal and cache).

Read it with its limits: one run (n = 1); 50 gateway calls; about 2.5 USD for the research and about 9 USD for the
verifier, which re-read 12 whole arXiv sources: this run used the optional full-text verification (`--fulltext`), off by
default in v0.5.1; the same question with the default settings cost 2.99 USD in total. Two blind judges of other model families found 2 errors in 14 claims
of this report checked against a common reference set (14 %); this is one case, not a benchmark.
