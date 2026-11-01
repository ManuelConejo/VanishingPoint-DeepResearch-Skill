# Licence, archive status and maintenance of five Python retry libraries at 2026-10-31

## Executive Summary

Of the five repositories, two are maintained at T = 2026-10-31 under the stated definition (not archived and at least one default-branch commit in the 12 months before T): jd/tenacity and hynek/stamina. The other three (litl/backoff, invl/retry, rholder/retrying) are not.

jd/tenacity is licensed Apache-2.0, is not archived, and its last default-branch commit before T is dated 2026-10-12 [2]. hynek/stamina is licensed MIT, is not archived, and its last default-branch commit is dated 2026-10-19 [5]. Both therefore fall inside the window 2025-10-31 to 2026-10-30.

litl/backoff is licensed MIT, is flagged as archived, and its last default-branch commit is dated 2023-01-20 [1]; it fails both conditions. invl/retry has the SPDX field NOASSERTION in the repository record [3], but its LICENSE file carries the Apache License, Version 2.0 notice [6], so the identifier is Apache-2.0 by our reading of that file; it is not archived, and its last default-branch commit is dated 2016-05-12 [3]. rholder/retrying is licensed Apache-2.0, is not archived, and its last default-branch commit is dated 2016-06-07 [4]. Both of these are unmaintained because they have no commit in the window, not because they are archived.

Two cautions. First, the archived flag and the licence field are current values (as of the day of the query), not values as of T, and GitHub gives no archiving date [1][2][3][4][5]; a repository archived between T and the query could not be detected, although for the three non-maintained repositories the conclusion would not change since each already lacks a recent commit. Second, the repository-wide push date (pushed_at) differs from the default-branch commit date for backoff, retry and retrying [1][3][4]; we use the commit date only, as the question asks. PyPI release dates corroborate the picture only loosely: tenacity 9.2.1 was published 2026-10-07 [7] and stamina 26.1.0 on 2026-04-13 [8], while the single releases we looked up for backoff, retry and retrying date from 2022, 2016 and 2025 [9][10][11]; none of these is shown to be the latest release. Fewer than ten sources carry this report; all are primary repository records read through the gateway.

## Introduction

The question asks, for five Python retry libraries on GitHub (litl/backoff, jd/tenacity, invl/retry, rholder/retrying, hynek/stamina), their SPDX licence, whether the repository is archived, the date of the last commit on the default branch, and whether the project is maintained, where maintained means not archived and at least one commit on the default branch in the 12 months before T. T is 2026-10-31, given in ISO form by the instruction; documents dated on or after T are not served. The 12-month window is therefore 2025-10-31 to 2026-10-30.

Plugin used: code. The plugin is designed for borrowing questions (a project X and a project Y); this question has no X, so no capsule, no target seam, and no GO/WATCH/NO-GO verdicts were used. Each repository was pinned at the SHA of its default-branch head before T as served by the gateway, and the verdict scale used here is maintained / not maintained. The report is in English. Mode: standard. Reading was done through the gateway only, with no clone and no execution of any code.

Method in five lines: the question was framed as per-repository criteria; four search sub-agents ran (three in the first wave, one complement); the repository records, head commits, one licence file, PyPI release dates and one Software Heritage visit were read; no verification occurred during collection; a single downstream verification follows.

Assumptions. (1) "Last commit date" means the committer date of the last commit of the default branch before T, as the gateway selects it; if the intended meaning were the repository's last push, backoff, retry and retrying would show later dates [1][3][4], but none of them would become maintained by the commit-based definition given in the question. (2) The licence of invl/retry is taken as Apache-2.0 from its LICENSE file text [6]; if the asker wants only the machine-detected value, the answer is NOASSERTION [3]. (3) The archived flag is read as of the query day; this would matter only for a repository archived after T.

## Main Analysis

### Finding 1 — Licences: three Apache-2.0, two MIT, with one needing a file reading

The repository records give jd/tenacity as Apache-2.0 [2], rholder/retrying as Apache-2.0 [4], litl/backoff as MIT [1] and hynek/stamina as MIT [5]. For each of these four, the record states the licence status as detected, with the licence file at path LICENSE, and the licence at the head SHA matches the headline value [1][2][4][5]. deps.dev reports the same licence for these four [1][2][4][5].

The fifth, invl/retry, is the exception: its record gives the SPDX identifier NOASSERTION, with the LICENSE file detected but deps.dev calling it "non-standard" [3]. Following the plugin's licence rule (read the file when the field is NOASSERTION), the LICENSE file at SHA c3f386aa279b130b37a4a4e91e758c7f02ec898c was read. It is 545 bytes and contains "Copyright 2014 invl", "Licensed under the Apache License, Version 2.0" and the apache.org licence URL, but not the full licence body [6]. This is why automated detectors fail to assign an identifier; the notice names the Apache License, Version 2.0, which corresponds to SPDX Apache-2.0. That mapping is our reading of the file, not a field returned by the gateway.

Consequence: the answer is Apache-2.0 for tenacity, retry and retrying, and MIT for backoff and stamina. The retry value rests on a short licence notice rather than a full licence text [6], and the record itself says NOASSERTION [3]. Verdict: established for four repositories; probable for invl/retry.

### Finding 2 — Archived status: only litl/backoff is flagged archived

The record of litl/backoff shows archived true [1]. The records of jd/tenacity, invl/retry, rholder/retrying and hynek/stamina show archived false [2][3][4][5].

The gateway states for every record that repository metadata is current (as of the query) and not as of T, and that GitHub gives no archiving date [1][2][3][4][5]. This means we cannot tell when backoff was archived, nor exclude that one of the four non-archived repositories was archived between T and the query. We saw no source on the archiving date of backoff.

Consequence: for the maintenance test, backoff fails the "not archived" condition on current data. The other four pass that condition. Because the three repositories that are not maintained for other reasons (see Finding 4) fail the commit condition regardless, the only maintenance answer sensitive to this caveat would be tenacity or stamina becoming archived after T, for which there is no evidence in the records [2][5]. Verdict: established as of the query day; open as of T exactly.

### Finding 3 — Last default-branch commit: two recent, three old

The gateway selects the last default-branch commit with a committer date before T. The results are: hynek/stamina 2026-10-19 on branch main, SHA 5c13c8e0b4bc5faa54914115a8c796934ba6da9d [5]; jd/tenacity 2026-10-12 on branch main, SHA 32ac68f0941319c0d2f4fb927f96e4ee29bb46c6 [2]; litl/backoff 2023-01-20 on master, SHA d82b23c42d7a7e2402903e71e7a7f03014a00076 [1]; rholder/retrying 2016-06-07 on master, SHA 1d5699348d707e377aad7488da6a8a1b48a65933 [4]; invl/retry 2016-05-12 on master, SHA c3f386aa279b130b37a4a4e91e758c7f02ec898c [3]. The three older heads were confirmed by a second, independent head query [1][3][4].

A trap exists: the repository-wide pushed_at differs from the default-branch commit date for the three older repositories (backoff 2024-05-02, retry 2024-07-05, retrying 2021-08-15), and is not a default-branch commit date [1][3][4]. For tenacity the push date 2026-10-12 and for stamina 2026-10-19 are within seconds of the commit date [2][5]. Using pushed_at would wrongly suggest activity in 2024 for backoff and retry.

Software Heritage records a last full visit of the stamina origin before T on 2026-10-30, with a snapshot [12]. Verdict: established for the dates as defined (gateway selection); the date definition is the main qualifier.

### Finding 4 — Maintenance verdict against the 12-month window

Applying the definition (not archived and a commit between 2025-10-31 and 2026-10-30): jd/tenacity is maintained, since it is not archived and its last commit is 2026-10-12 [2]. hynek/stamina is maintained, since it is not archived and its last commit is 2026-10-19 [5]. litl/backoff is not maintained, since it is archived and its last commit, 2023-01-20, precedes the window [1]. invl/retry is not maintained: it is not archived but its last commit, 2016-05-12, precedes the window [3]. rholder/retrying is not maintained for the same reason, with a last commit of 2016-06-07 [4].

Qualifications. The definition is mechanical and says nothing about issue response or release cadence; a library can be stable and complete yet fail it, and a single commit in the window would suffice to pass it. We did not read commit content, so a recent commit could be trivial (we did not check). Of the two maintained repositories, we only know that a commit exists on the default branch in the window [2][5]. No source seen contradicts these verdicts.

Verdict: established for the stated definition. Three of five fail; the failure of backoff is doubly determined (archived and no commit in window), the other two by lack of commits alone.

### Finding 5 — Registry release dates give weak corroboration, and one identity oddity

PyPI release dates were looked up for one version per package, versions that were guessed or learned from a dependency graph, so the latest release of a package is not established by these lookups. tenacity 9.2.1 was published 2026-10-07 [7], consistent with an active tenacity repository [2]. stamina 26.1.0 was published 2026-04-13 [8], while the repository head is later (2026-10-19) [5], which is not a contradiction since a later release may exist. backoff 2.2.1 was published 2022-10-05 [9], before its last commit of 2023-01-20 [1]. retry 0.9.2 was published 2016-05-11 [10], one day before its last commit [3]. retrying 1.4.2 was published 2025-08-03 [11].

The retrying release deserves caution: the PyPI metadata of retrying 1.4.2 points to github.com/groodt/retrying, not to rholder/retrying [11]. The 2025 release therefore appears to come from a different repository than the one asked about, whose last commit is 2016 [4]. We have not established whether groodt/retrying is a fork or a continuation, and it is outside the question. A reader looking at PyPI activity alone could wrongly credit rholder/retrying with 2025 activity.

Consequence: registry dates do not change any verdict; they illustrate that package-level activity and repository-level activity can diverge. Verdict: open as corroboration (single releases, latest not established).

## Synthesis & Insights

Taken together, the records split the five libraries cleanly: tenacity and stamina are active and unarchived; backoff, retry and retrying are not active in the window. This is our analysis. The split follows the commit dates much more than the archive flag: only backoff is archived, while retry and retrying are unmaintained without being archived [1][3][4]. stamina depends on tenacity (its dependency graph lists tenacity 9.2.1 as a direct dependency, as read in the registry cross-check [7][8]), so the two maintained projects are also linked, a regularity the question did not ask for.

The main disagreement between ways of measuring is pushed_at versus default-branch commit date, which would make backoff and retry look recently touched [1][3]. The licence picture is uniform in permissiveness (MIT or Apache-2.0 across all five), with one detection gap for retry [1][2][3][4][5][6]. Composite capability: none, because the question is a factual lookup with no host project X and no mechanisms to assemble.

## Limitations & Caveats

The archived flag and licence field are current, not as of T, and GitHub gives no archiving date [1][2][3][4][5]. The commit dates rely on the gateway's selection of the last default-branch commit before T; they were confirmed by a second head query for three repositories, and for the other two (tenacity, stamina) the repo-info record carries the date [2][5], with an additional head query for stamina [5]. Commit content was not examined. PyPI cross-checks cover one guessed or inherited version per package and do not establish latest releases [7][8][9][10][11]; a first attempt to list versions failed because the tool needs an exact version. Software Heritage provenance was run for one repository only, hynek/stamina. The Apache-2.0 attribution for invl/retry is a reading of a short notice [6]. Eight gateway calls for the version listing were refused or failed and brought nothing. The plugin's borrowing framework (capsule, seams, verdicts) did not apply and was not used. Fewer than ten sources carry the report. Stopping: one complement wave was run after the first wave; the formal two-consecutive-empty-waves saturation rule was not exercised, since the question's facts were fully answered by the primary records.

## Recommendations

For a reader choosing among these libraries on maintenance grounds under this definition, tenacity and stamina qualify, while backoff, retry and retrying do not. To watch: whether tenacity and stamina keep committing, and whether backoff's archiving date matters to the asker. To search further: the latest PyPI release of each package, the archiving date of litl/backoff, the relationship between rholder/retrying and groodt/retrying, and a full licence text for invl/retry if a strict SPDX declaration is needed.

## Bibliography

[1] litl/backoff, repository record at default-branch head, 2026, repo:litl/backoff@d82b23c42d7a7e2402903e71e7a7f03014a00076, basis: record
[2] jd/tenacity, repository record at default-branch head, 2026, repo:jd/tenacity@32ac68f0941319c0d2f4fb927f96e4ee29bb46c6, basis: record
[3] invl/retry, repository record at default-branch head, 2026, repo:invl/retry@c3f386aa279b130b37a4a4e91e758c7f02ec898c, basis: record
[4] rholder/retrying, repository record at default-branch head, 2026, repo:rholder/retrying@1d5699348d707e377aad7488da6a8a1b48a65933, basis: record
[5] hynek/stamina, repository record at default-branch head, 2026, repo:hynek/stamina@5c13c8e0b4bc5faa54914115a8c796934ba6da9d, basis: record
[6] invl/retry, LICENSE file at SHA, 2016, repo:invl/retry/LICENSE@c3f386aa279b130b37a4a4e91e758c7f02ec898c, basis: record
[7] tenacity 9.2.1, PyPI release record, 2026, pypi:tenacity@9.2.1, basis: record
[8] stamina 26.1.0, PyPI release record, 2026, pypi:stamina@26.1.0, basis: record
[9] backoff 2.2.1, PyPI release record, 2022, pypi:backoff@2.2.1, basis: record
[10] retry 0.9.2, PyPI release record, 2016, pypi:retry@0.9.2, basis: record
[11] retrying 1.4.2, PyPI release record, 2025, pypi:retrying@1.4.2, basis: record
[12] hynek/stamina, Software Heritage visit 474 (snapshot swh:1:snp:757380facf765902d79663bfcfbd48059e00ae73), 2026, provenance:https://github.com/hynek/stamina, basis: record

## Methodology Appendix

Process: six angles (one per repository, plus a registry and provenance cross-check); four search sub-agents (three in the first wave, one complement wave that read the retry LICENSE file and re-confirmed three heads); the plan of findings was kept (licences, archived, dates, maintained verdict, corroboration); no plan change. The complement wave brought one new eligible document (the retry LICENSE file); the stopping rule of two empty consecutive waves was not reached and the run stopped after the complement because the question was fully answered (stated as a deviation). The step 4.7 batch read of possibles listed 0 candidates.

Source coverage: active: github-repo records, versions (PyPI, deps.dev), provenance (Software Heritage), code engines of the plugin. Skipped or degraded: none by key (VP_GITHUB_TOKEN present); the version-listing command needed exact versions, so latest releases were not established. Suggestions: none.

Verification: rule "verified = what carries a decision": 30 claims checked (executive-summary facts and finding verdicts); the other sentences of the findings are traceable by their `[n]` and were not checked. Result: 1 FOUND (`A11`, the Apache notice of the retry LICENSE file, `[6]`), 29 SOURCE-UNAVAILABLE, 0 DISTORTED, 0 ABSENT, 0 INVALID, 0 removals. The 29 SOURCE-UNAVAILABLE claims cover `[1]`, `[2]`, `[3]`, `[4]`, `[5]`, `[7]`, `[8]`, `[9]`, `[10]`, `[11]` and `[12]`: the verifier could not access them because the card cited repository records and registry entries in a form it does not accept as a code source (it expects a file path and a SHA in hexadecimal). This is a limit of the annex format, not a contradiction by the sources; there is no re-verification in this mode, so these claims are kept flagged as unverified (SOURCE-UNAVAILABLE), and every date, licence and archived flag of this report except the retry notice rests on the gateway records as read by the searchers. No DISTORTED correction and no removal were made.

Plugin biases looked for: licence before the code (applied to retry), pin to a SHA (applied: every repository is pinned), abandoned repositories as context (backoff, retry, retrying), popularity not used as proof.

Cost: gateway calls counted 17 (repo-info 5, repo-head 4, repo-file 1, versions 5 accepted, provenance 1, plus refused version calls not counted); four searchers; the cost of the verifier is added after section 7. Mode: standard. Machine annex files: card.json, result.json, mechanisms.json (not produced: no borrowing mechanism), verdicts.json.

Summary: jd/tenacity (Apache-2.0) and hynek/stamina (MIT) are maintained at 2026-10-31, while litl/backoff (MIT, archived, last commit 2023-01-20), invl/retry (Apache-2.0 by file reading, last commit 2016-05-12) and rholder/retrying (Apache-2.0, last commit 2016-06-07) are not.
