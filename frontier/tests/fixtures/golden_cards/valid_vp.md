Rebound is an agentic creative aid: it proposes ideas and test plans judged by models, with no guarantee - unlike the rest of VanishingPoint, whose claims are measured.
# Idea card: Preprints with shorter titles collect more citations at two years because search engine...

T 2026-11-14 | domain: scientometrics | language: en | valid_vp | Already tried here: not checked (no project_dirs given) | assembled by tools/card.py from the JSON files of this directory; this card is not a certification of novelty or value.

**Recommendation: DIG**: The retrieval mechanism held in a randomised test with a working positive control, so the citation step (T2) is now worth its day.

## Idea
Preprints with shorter titles collect more citations at two years because search engines retrieve them more often. If so, shortening titles is a cheap lever for visibility.
Gain that would justify the effort: Knowing whether title length acts through retrieval (a causal lever authors control) or only marks journal prestige (no lever).

## Prior art: Partially
- Closest: Title length and citation counts across fields (2019), doi:10.1000/titles.2019 [FOUND]; differs: Observational association only; no retrieval mechanism and no intervention on titles.
- Closest: Search-engine retrieval of scholarly records by title terms (2021), arxiv:2101.00001 [FOUND]; differs: Studies retrieval rank, not citations.
- Searched: VP prior-art run vp-2026-11-14-short-titles-prior-art: 2 essential elements (E1 title length and citations; E2 retrieval mechanism), engines of plugins/cs-ai...
- Materials: anomalies: The title-length association weakens after adjustment for journal b...; transferable methods: Query-log retrieval experiments with controlled title variants.; contradictory results: Prestige explains a large part of the association.

## Hypotheses
- H1 (load-bearing): Shorter titles rank higher in scholarly search engines for typical topical queries. | for: arxiv:2101.00001 [FOUND] | against: none
- H2 (load-bearing): Higher retrieval rank translates into more citations at two years. | for: doi:10.1000/titles.2019 [FOUND] | against: doi:10.1000/prestige.2020 [DISTORTED]
- R1 (rival): Journal prestige drives both short titles (house style) and citations; title length has no effect... | why plausible: Prestige explains a large part of the association in the closest work. | for: doi:10.1000/prestige.2020 [DISTORTED]
- V1 (repairable variant): Title informativeness (query-term coverage), not length, drives retrieval. (repairs: Length may only proxy for term match.)

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

## Critique of the protocol: openai via vp-contradictor
T1 is sound if the shortening rule is frozen; T2's clarity rating needs the L0 control.
- [major] T1 missing_control: Nothing shows the index is sensitive to titles at all. -> fixed: Positive control added: dropping the query term must lose rank.
- [blocking] T2 leakage: An LLM rating title clarity may know which papers became famous. -> fixed: L0 control: titles alone must not predict citation rank.
- Critic trap verdicts (4 traps per test): T1 not returned by this route; T2 not returned by this route
- Raw answer of the critic: critique-raw.json (sha256 6cf547206f52...)

Marks: [REVISION] test_revision.json: deciding-test weakness has no receipt; record one focused revision or no change with a reason | [OVERLAP-LEDGER] prior_art.json doi:10.1000/titles.2019: state overlap_dimensions (problem/method/data/setting/claim) | [OVERLAP-LEDGER] prior_art.json arxiv:2101.00001: state overlap_dimensions (problem/method/data/setting/claim)
## Result
Executed T1 with docker (exit code 0): Mean paired rank gain 4.1 positions, 95% CI [3.4, 4.8]; positive control lost rank as required. Decision: **continue** (CI above 0 and estimate >= 3: continue.)

## Decision log
- Before (T1, researcher, 2026-11-14T11:00:00Z): If T1 shows no gain I drop the idea; if it shows a gain I run T2.
- After (T1, researcher, 2026-11-14T12:10:00Z): Gain seen; I schedule T2 next week.

<!-- frontier inputs sha256:0ffcb3cc4221f70d378670cb01d1042ad4865a13045fb2e6a9f7b8edb83cb4e3 -->
