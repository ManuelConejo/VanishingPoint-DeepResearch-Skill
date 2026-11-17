Rebound is an agentic creative aid: it proposes ideas and test plans judged by models, with no guarantee - unlike the rest of VanishingPoint, whose claims are measured.
References not verified (VP not installed)

# Idea card: Preprints with shorter titles collect more citations at two years because search engine...

T 2026-11-14 | domain: scientometrics | language: en | valid_novp | Already tried here: not checked (no project_dirs given) | assembled by tools/card.py from the JSON files of this directory; this card is not a certification of novelty or value.

**Recommendation: TEST FIRST**: Prestige may explain the whole association, and the cheap paired retrieval test (T1) separates the two readings in an afternoon.

## Idea
Preprints with shorter titles collect more citations at two years because search engines retrieve them more often.
Gain that would justify the effort: Assumed: knowing whether title length is a lever authors control. (assumption: the user was not there to answer)

## Prior art: Partially
- Closest: Title length and citation counts across fields (2019), doi:10.1000/titles.2019 [unverified]; differs: Observational association only; no retrieval mechanism.
- Searched: Host web search, 6 queries on title length, citations and retrieval rank, documents dated before 2026-11-14.
- Materials: anomalies: none; transferable methods: Query-log retrieval experiments with controlled title variants.; contradictory results: Prestige explains a large part of the association.

## Hypotheses
- H1 (load-bearing): Shorter titles rank higher in scholarly search engines for typical topical queries. | for: arxiv:2101.00001 [unverified] | against: none
- H2 (load-bearing): Higher retrieval rank translates into more citations at two years. | for: doi:10.1000/titles.2019 [unverified] | against: doi:10.1000/prestige.2020 [unverified]
- R1 (rival): Journal prestige drives both short titles and citations. | why plausible: Reported as a large confounder in the closest work. | for: doi:10.1000/prestige.2020 [unverified]
- V1 (repairable variant): Title informativeness, not length, drives retrieval. (repairs: Length may only proxy for term match.)

## Minimal tests, ranked by value of information for the next decision relative to cost
Order: T1 > T2. Basis: value of information for the next decision relative to cost.
### T1: Paired retrieval experiment: short vs long title of the same record in an offline index
- Competing: H1 vs R1. Predictions: H1: increase [3, 10] rank positions (mean paired gain); R1: no change [-1, 1] rank positions (mean paired gain). Compatible with both: A rank gain of 1 to 3 positions: too small to separate retrieval fr.... Unexpected under both: Long variants rank clearly higher (difference below -3 positions)
- Decisive intervention (randomisation, positive_control): For each of 200 records, randomise which title variant (original long vs shortened, same key terms) is indexed first; the abstract is held fixed.
- Decision rule, fixed before observation: continue if 95% CI of the mean paired rank gain lies above 0 and the point estimate is at least 3; revise if CI above 0 but entirely below 3 positions: real but too small; test the infor...; stop if CI entirely below 1 position (equivalence to no useful effect); indeterminate if Any other outcome; report it, do not extend n after looking. Equivalence: margin 1 rank position.
- Sensitivity: smallest useful effect 3 rank positions on the first results page; noise SD of paired rank difference about 5 positions (pilot of...; replications 200 records x 1 query each; simulation (tools/sim.py, paired, n=200, seed 20261114, rerun by check.py): distinguishes the scenarios (lowest P(expected decision) = 0.803)
- Feasibility: data 200 open records with abstracts (public metadata dump); an offline...; human time about 4 hours to write shortened titl...; compute minutes on a laptop CPU; risk the shortening rule may drop key terms; guarded by the positive con...
- Traps: proxy rank in an offline BM25 index vs target retrieval by real readers of the records; 1 variant(s) tested, choice fixed before (One shortening rule (drop subtitle and stop wor...); positive control: Records whose shortened title drops the query term must lose rank.; design data (the 20 pilot records used to set the SD) kept apart from confirmation data (200 other records drawn after the rul...)
- L0 leakage control (C-075): not applicable: No language model judges anything in this test.
### T2: Within-journal comparison of citations by title length, with an LLM rating of title clarity
- Competing: H2 vs R1. Predictions: H2: increase [1.1, 1.5] ratio of mean citations, short over l...; R1: no change [0.95, 1.05] ratio of mean citations, short over l.... Compatible with both: A ratio between 1.05 and 1.10. Unexpected under both: A within-journal ratio below 0.95 (long titles cited more)
- Decisive intervention (permutation, negative_control): Permute title length within journal-year strata to build the null; negative control: page count, which neither hypothesis links to retrieval.
- Decision rule, fixed before observation: continue if Permutation p < 0.01 and ratio >= 1.10; revise if Ratio significantly above 1 but below 1.10; stop if Ratio CI inside [0.95, 1.05]; indeterminate if Any other outcome. Equivalence: margin ratio within [0.95, 1.05].
- Sensitivity: smallest useful effect ratio 1.10; noise overdispersed counts; bootstrap SE of the log-ratio about...; replications 2000 short and 2000 long titles withi...; simulation not applicable: Count data with overdispersion: the two-arm normal model of sim.py does not fit; the permutation null plays...
- Feasibility: data open citation counts for preprints posted in 2022-2023; human time 1 day; compute under one hour CPU; risk journal of record missing for unpublished preprints
- Traps: proxy citations at two years after posting vs target being read and used by other researchers; 2 variant(s) tested, choice fixed before (Length in words and in characters both reported...; correction: Holm correction over the two length measures; o...); positive control: Known effect of open access on citations must be recovered in the s...; design data (2021 preprints used to choose the strata) kept apart from confirmation data (preprints posted in 2022 and 2023)
- L0 leakage control (C-075): L0 control: the same LLM rates the titles alone and must not predict citation rank above chance; if it does, its clarity rating leaks hindsight (C-075) and i...
Scenarios:
- If T1 shows a gain of at least 3 positions, then run T2 to see whether the gain reaches citations (T1 is cheap and removes the mechanism doubt first)
- If T1 is equivalent to no gain, then stop; T2 would only measure prestige (Without retrieval the idea has no lever)

## Critique of the protocol: claude via subagent
Critique: same family (no independent critic available)
Same-family sub-agent: T2 needs the L0 control; T1 needs a positive control.
- [major] T1 missing_control: No evidence the index reacts to titles. -> fixed: Positive control added.
- [minor] all other: Ranking scenarios ignore the cost of building the index. -> open: Left to the researcher.
- Critic trap verdicts (4 traps per test): T1 4 addressed; T2 3 addressed, 1 unclear
- Raw answer of the critic: critique-raw.txt (sha256 68da1c7d5f5e...)

Marks: [REVISION] test_revision.json: deciding-test weakness has no receipt; record one focused revision or no change with a reason | [OVERLAP-LEDGER] prior_art: registered VP run unavailable | [OVERLAP-LEDGER] prior_art.json doi:10.1000/titles.2019: state overlap_dimensions (problem/method/data/setting/claim) | [OVERLAP-LEDGER] prior_art.json doi:10.1000/titles.2019: query attribution unknown | [OVERLAP-LEDGER] prior-art queries not checked: no available VP journal
## Result
Plan only: no isolated container engine (docker or podman) found on PATH.

## Decision log
- Before (T1, assumption, 2026-11-14T11:00:00Z): Assumed (researcher absent): would drop the idea if T1 shows no rank gain.

<!-- frontier inputs sha256:4c0f05e1dd722f956ef67946941e70350ae125eb6429e11031fc159e96538e83 -->
