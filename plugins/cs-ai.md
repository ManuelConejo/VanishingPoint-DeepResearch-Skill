# Plugin cs-ai - computer science and artificial intelligence (2026-10-26)

Read by the engine (SKILL.md). Four fixed sections. Every source says where its facts were established (documentation, probe date); "not established" = the information was not established anywhere. Every key is optional: without a key, the source is skipped with a receipt `credential_missing` or `rate_limited`, never "nothing found".

## Sources

Block read by `tools/gateway.py` (format: README.md, "Adding a plugin"); engines that are not wired are declared anyway: the gateway lists them `not_wired` and refuses them cleanly. Access marked according to `ACCESS-POLICY.md`: `api` (level 1, documented API, robots.txt has no effect), `page` (level 2: public page, pacing 1 request / 2 s / host, declarative UA, cache, stop on 429/403), `browser` (level 2b: public page behind a JS challenge, driven browser, same pacing), `tos_forbidden` and `technical_block` (level 3: listed, disabled). Probes below are dated 2026-10-26 unless stated.
```sources
engines: openalex, crossref, arxiv, europepmc, dblp, semantic-scholar, hf-papers, catalyzex, datacite, hal, zenodo, openaire   # wired: openalex, crossref, arxiv, europepmc ; the others: not wired (datacite, hal: planned ; zenodo, openaire: options)
cap: 60                                  # safety cap on calls
keys: OPENALEX_KEY, S2_API_KEY, OPENAIRE_TOKEN   # optional ; resolution KEYS.md (env NAME, ~/.config/vp/<name>.key) ; never required, never displayed
useful_when: semantic-scholar=citations, reference graph, recent cs/AI, citing papers, recommendations, state of the art ; openaire=European institutional repositories, funded projects, publication-data-software links ; openalex=broad searches, citation chaining, outside arXiv   # free-key sources ; read by tools/check_keys.py --suggest
access: openalex=api, crossref=api, arxiv=api, europepmc=api, dblp=api, semantic-scholar=api, hf-papers=api, catalyzex=page, datacite=api, hal=api, zenodo=api, openaire=api   # ACCESS-POLICY.md ; level-2 pacing on `page` (to be wired)
disabled: openreview=browser, google-scholar=browser, alphaxiv=technical_block, base=technical_block, ieee=technical_block, elicit=technical_block   # listed, not called ; reason under "Set aside"
```

Recommended call order: 1 -> 4 and 9 -> 10 to search, 5 -> 8 to chain and link to code, 2 to resolve; today only the wired engines of the block above (openalex, crossref, arxiv, europepmc) can be called, the others are listed for the day they are wired and the gateway refuses them with a receipt. Cut-off date T of the question: every datable source is bounded at **the day before T** on the provider side, then re-checked locally (every known date < T; a partial date counts as its upper bound) (gateway rule).

1. **OpenAlex** (open bibliographic index) - `access: api`
   - Endpoint: `https://api.openalex.org/works`; resolution: `/works/doi:<DOI>`, `/works/pmid:<PMID>`, `/works/<id>`.
   - Query: `search=<text>`, `per_page=<n <= 50>`, `select=<fields>`, `filter=to_publication_date:<day before T>` (extra filters possible, e.g. `openalex_id:a|b`). Abstract rebuilt from `abstract_inverted_index`.
   - Date bound: yes (`to_publication_date`), then **mandatory Crossref re-check** (deposit `created` AND publication `issued` < T); works without a Crossref DOI are refused.
   - Key: OPTIONAL (`OPENALEX_KEY`: env or `~/.config/vp/openalex_key.key`, KEYS.md; never displayed). Without key: shared budget 0.10 USD/day (about 100 searches), 429 possible from the 1st call; with a free key: 1 USD/day.
   - Rate: gateway 0.2 s between calls; on 429 no retry, Crossref fallback reported in the receipt. Measured gain in biomedicine: none; outside medicine: not measured.

2. **Crossref** (resolve a DOI, deposit and publication dates, retractions) - `access: api`
   - Endpoint: `https://api.crossref.org/works`; `/works/<DOI>`.
   - Query: `query.bibliographic=<text>`, `rows=<n>`, `select=DOI,title,issued,created,container-title,author,type`, `filter=until-created-date:<day before T>,until-pub-date:<day before T>`; batch: `filter=doi:a,doi:b` (100 per call). Declarative `mailto=` parameter (VP_CONTACT).
   - ACM proceedings without touching dl.acm.org: `filter=prefix:10.1145` + `query.bibliographic=` (trick seen in the open-source `openags/paper-search-mcp`, `ap/acm.py`); the ACM PDF remains a paywall (`technical_block`).
   - Mechanical retractions: `filter=update-type:retraction` (76,441 notices on 2026-10-26, probe 200), field `update-to`; for one work: `has-update:1` then read `update-to`; Retraction Watch distributed by Crossref (GitLab CSV `crossref/retraction-watch-data`, daily; RW data licence: not established).
   - Date bound: yes (`created` AND `issued`).
   - Key: none.
   - Rate: gateway 0.25 s; published limit: not established. Decided role: RESOLVE, not SEARCH (verdict measured in biomedicine only).

3. **arXiv API** (preprints cs.*, stat.ML) - `access: api` (robots `Disallow: /` on export.arxiv.org has no effect on the documented API, level 1)
   - Endpoint: `https://export.arxiv.org/api/query` (Atom).
   - Query: `search_query=` with prefixes `ti:`, `abs:`, `au:`, `cat:`, `all:`, operators `AND`, `OR`, `ANDNOT`, quoted phrases; `id_list=<ids>` to check a reference; `start=`, `max_results=` (<= 100 per page); `sortBy=relevance|submittedDate`. Useful fields: `published` (date of v1), `updated`, `arxiv:comment` ("announced" venue), `arxiv:doi`.
   - Date bound: **yes** (official manual: "The API provides one date filter, submittedDate"): `submittedDate:[YYYYMMDDTTTT TO YYYYMMDDTTTT]` (GMT) inside `search_query`, upper bound = day before T 2359; <= 30,000 results, slices <= 2,000; local re-check on `published` < T kept.
   - Key: none.
   - Rate: 1 request every 3 s (arXiv terms of use); error marker "Rate exceeded".

4. **dblp** (computer science proceedings and journals) - `access: api`
   - Endpoint: SPARQL `https://sparql.dblp.org/sparql` (JSON); the search API `https://dblp.org/search/publ/api?q=&format=json` served an anti-robot page (HTTP 202) when probed on 2026-10-22: to be typed `bot_challenge`, not "empty" (`browser` route possible, not probed). XML dump `dblp.org/xml/` (301 to Dagstuhl, exists) = offline option.
   - Query (SPARQL): filter `CONTAINS(LCASE(?title), "<phrase in lowercase>")`, fields `dblp:title`, `dblp:yearOfPublication`, `dblp:doi`, `dblp:publishedIn`, `LIMIT/OFFSET` (100 per page).
   - Date bound: year only (`yearOfPublication` < year of T, strictly).
   - Key: none. Rate: 2 s local; published limit: not established.

5. **Semantic Scholar** (citation graph, snippets, recommendations; base of Elicit, Consensus, Undermind, OpenScholar) - `access: api` (optional key)
   - Endpoint (doc `semanticscholar.org/product/api`, swagger): `/paper/search`, `/paper/search/bulk` (1,000 per call), `/snippet/search`: 429 almost systematic without key ("1,000 req/s shared among all anonymous users"); `/recommendations/v1/papers/forpaper/arXiv:<id>`: 200 in a demo on 2026-10-25 (10 neighbours).
   - Query: recommendations from a winning source; search only with a key.
   - Date bound: **yes**: `publicationDateOrYear=<start>:<end>` (YYYY-MM-DD) and `year=`; local re-check kept.
   - Key: OPTIONAL (`S2_API_KEY`), free by form, 1 req/s announced; address restriction and issuance to webmail accounts: not established. Licence: attribution mandatory, data CC BY-NC / ODC-BY, no redistribution. Decision: option once the key is obtained.
   - Measured trap: an arXiv identifier was resolved to another paper; **always re-check the resolved title**. Measured contribution (computer science and physics, exploratory, measured on our benches): removing S2 costs 8.04 points of total recall.

6. **HF Papers** (paper -> repository, models, datasets link) - `access: api`
   - Endpoint: `https://huggingface.co/api/papers/search?q=`; `https://huggingface.co/api/papers/<arxiv>` (fields `githubRepo`, `githubStars`, `publishedAt`); `https://huggingface.co/api/{models|datasets|spaces}?filter=arxiv:<id>&limit=&full=true`.
   - Query: by arXiv identifier without version suffix; models, datasets and Spaces are community-provided, "unverified"; their likes are not GitHub stars.
   - Date bound: no provider filter (`sort=created_at` only); `publishedAt` serves the local re-check.
   - Key: none. Rate: anonymous **500 req / 5 min / IP** (doc hub/rate-limits, `ratelimit-policy` header observed); 2 s local. Coverage: ML-centred; about 27 % of papers have a link.

7. **CatalyzeX** (HF fallback for paper -> code) - `access: page` (undocumented JSON endpoint: level-2 regime)
   - Endpoint: `https://www.catalyzex.com/api/code?src=arxiv&paper_arxiv_id=<id>`; undocumented.
   - Rule: accept a repository only if its README cites the arXiv identifier or the title (Paper2Code false positive in a demo: right 1 case out of 2).
   - Date bound: not established. Key: none. Rate: not established -> level-2 pacing (1 request / 2 s).

8. **Europe PMC** (citing/references chaining; cs coverage almost nil) - `access: api`
   - Endpoint: `https://www.ebi.ac.uk/europepmc/webservices/rest/search?format=json&resultType=lite|core&pageSize=&query=`; `/{src}/{id}/citations`, `/references` (pageSize 1000).
   - Bound: `firstIndexDate` AND `firstPublicationDate` < T. Key: none. Rate: 0.25 s gateway.
   - Relevance: 0/5 on the arXiv frontier (measured on our benches); call only to chain from a source already found.

9. **DataCite REST** (DOIs of datasets and software, absent from OpenAlex) - `access: api`; not wired
   - Endpoint: DataCite REST API (doc `support.datacite.org/docs/api`); established parameters: `query=<text>`, `resource-type-id=software`; exact host URL and path: not established (to be recorded when wired).
   - Date bound: year only (`published=<YYYY>`); mandatory local re-check on the dates of the record.
   - Key: none. Rate: 3,000 req / 5 min, User-Agent with contact; probe 200 on 2026-10-26. Role: fill the "artefacts" gap (data, code with DOI).

10. **HAL, computer science domain** (INRIA/CNRS theses and reports, French-speaking) - `access: api` (robots `Disallow: /search/` on the API host has no effect, level 1; same adapter as `law.md`, Sources 7)
    - Endpoint: `https://api.archives-ouvertes.fr/search/?q=&fq=level1_domain_s:<cs code>&wt=json&fl=halId_s,title_s,producedDate_s,doiId_s,uri_s,docType_s,authFullName_s&start=&rows=100`.
    - Date bound: yes, `producedDate_tdate`, `submittedDate_tdate`; local re-check on `producedDate_s`.
    - Code of the computer science domain in `level1_domain_s`: **not established** (reference list `/ref/` under robots; to be recorded at the first call; now readable as `page`).
    - Key: none. Rate: 1 s local; published limit: not established.

Seen in the open-source `openags/paper-search-mcp` (MIT; evaluated on 2026-10-26) and absent from our plugins: **IACR ePrint** (cryptography; no API: HTML scraping of `https://eprint.iacr.org/search?q=` then PDF `eprint.iacr.org/<id>.pdf`; no date filter; `access: page`, level-2 pacing with a declarative UA - not the random browser UA of that repository; option not wired, to be probed); **OpenReview**: that repository queries `api2.openreview.net/notes/search` with a declarative UA and typed errors, to be re-probed from the gateway before concluding to a challenge (our probe of 2026-10-26: 403); **CiteSeerX** (JSON API `citeseerx.ist.psu.edu/api/search`, judged intermittent by the repository itself, Wayback redirections: set aside); **Google Scholar**: pure HTML scraping with a random browser UA, consent cookie, captcha detected but never solved (error, cool-down 60-900 s), no date filter -> for us `browser`, disabled, stop at the first captcha.

Options (declared, not wired, to be measured before becoming a default): **Zenodo REST** (doc `developers.zenodo.org`; `size <= 25`, filter `publication_date:[a TO b]`, 30 req/min on search, metadata CC0; DataCite already covers its DOIs) `access: api`; **OpenAIRE Graph API** (doc `graph.openaire.eu/docs`; filters `fromPublicationDate`/`toPublicationDate`, CC-BY; **60 req/h without token**, 7,200/h with the free token `OPENAIRE_TOKEN`; useful for chaining or with a token) `access: api`; **ACL Anthology** (static files `anthology.bib.gz`, `<id>.bib`, repository `acl-org/acl-anthology`, CC BY 4.0; no API; duplicate of dblp/OpenAlex, useful to resolve a PDF) `access: page`; **Ai2 Asta MCP** (key by form, licence "academic and non-commercial research"; direct S2 is enough) `access: api` (key required).

Set aside, do not query: **Papers with Code** (closed, 302 to HF Trending; archive CC BY-SA 4.0); **OpenReview** (`api2.openreview.net/notes` -> 403 ChallengeRequiredError; `access: browser`: can be enabled at level 2b for the reviews of a conference, disabled as long as the browser mode is not wired); **Google Scholar** (no API, robots `Disallow: /scholar`; `access: browser`, disabled: stop at the first captcha, level 3); **CORE** (without key 100 tokens/day, immediate 429; `api`, set aside for quota); **IEEE Xplore** (key on manual review, non-commercial, 403 without key; `technical_block`); **Springer Meta API** (key, terms not established, duplicate); **ORKG** (open reading, low value); **alphaXiv** (no public API, internal spec bearer/cookies/OAuth; `technical_block`); **Elicit, Consensus, scite, Undermind** (paid, third-party model call; `technical_block`); **BASE** (access by registered IP; `technical_block`); **NeurIPS proceedings, PMLR** (static HTML, duplicate of dblp/OpenAlex; `page`); **Perplexity, Exa** (third-party model call or key; option, never default).

## Discipline biases

Shared catalogue: `vp-bias-catalogue/1`, discipline file `cs-ai` (`usage = "signal"`, 12 biases `ai.*`, 20 verified references). Measurement of the catalogue (measured on our benches on 12 AI papers): apparent recall 5/7, but with the only citation verified in the text **0-1/7**; the absence biases (`ai.no_uncertainty`, `ai.overgeneralisation`) trigger on 30 to 50 % of the controls; on a fresh set no judge reaches the threshold -> **signals, never verdicts**, grid outside the product by default. Each line refers to what was observed and carries the catalogue id when one exists.
- **Preprint not peer-reviewed; "announced" venue** (no catalogue id). The venue read in the arXiv comment or a README is not the proceedings (observed: "ICLR 2026 not seen" for a baselines paper). An arXiv version can change its title (observed on a code-RAG paper renamed between versions): cite the version.
- **Self-reported scores, copied without re-reading** (`ai.reproducibility` when code, data or settings are missing). A figure without a `checked` mark in a card was copied from the paper by an agent, not re-read. "10x cheaper" held for 2 instances only (observed). Figures hallucinated by assistant models: a non-existent "HARD-109", false arXiv identifiers (measured on our benches: 5 false identifiers from an assistant model among 19 discrepancies).
- **Single run, no error bars** (`ai.seed_selection`, `ai.no_uncertainty`): "1 run per setting"; "no repetitions nor variance"; 3 runs without standard deviation (all observed on real papers). The ranking of methods changes with the number of seeds (Evolution or Illusion).
- **Saturated or contaminated benchmarks** (`ai.benchmark_contamination`, `ai.test_set_tuning`). "Contamination possible, the authors say so" (observed); the authors' own verification set saturated for a strong model. A result is comparable only at the same split, metric and budget.
- **LLM judge** (no catalogue id): an LLM judge's preference does not predict real use (measured on our benches); LLM self-evaluation fails (Si, Yang, Hashimoto); LiveIdeaBench scores by LLM judges on a keyword, "to avoid as ground truth"; a cheap judge loses (measured on our benches).
- **Cut-off date and temporal leakage** (`ai.leakage_split`, `ai.benchmark_contamination`). Models remember the corpus up to their cut-off; a result later than T may come from memory, not from search (measured on our benches: the memory-only probe scores 3/7). Live indexes = leakage (grep.app). Provider bounds are insufficient alone: mandatory local re-check (gateway rule).
- **Leakage through preprocessing or variables** (`ai.leakage_preprocessing`, `ai.illegitimate_features`), **shortcuts and confounding** (`ai.shortcut_confounding`): in the catalogue with their references (Kapoor-Narayanan, DeGrave), not observed in our own sets.
- **Weak or missing baselines** (`ai.weak_baselines`, `ai.unequal_budget`): gain "against no RAG" (+40.90 observed); meta-analysis "retrieval against draws at equal compute": none found; equal budget in calls but not in tokens.
- **Gain through length, not method**; **generalisation from a single benchmark** (`ai.overgeneralisation`): measured on our benches; "oracle >> retrieval" that reverses depending on the dataset (observed on CodeRAG-Bench).
- **Identifier resolution**: Semantic Scholar resolved an arXiv identifier to another paper (measured on our benches); the same arXiv number cited by a model can be an astrophysics paper (observed).
- **Retractions and errata** not flagged by the indexes: retracted/erratum states to be checked through Crossref (measured on our benches: 30/30 detected).

## Output format

The report keeps the eight sections of SKILL.md section 5 and the annex keeps the `card.json` / `result.json` formats of SKILL.md section 6: nothing here replaces them. What follows is what each finding states, in prose, about each retained study, and what the six `criteria` fields of `result.json` summarise for this discipline (one **study card** per retained reference, fields in this order):
1. **Full citation**: authors, exact title, year, venue with label `proceedings` / `announced (arXiv comment or README)` / `preprint`, arXiv identifier **with version** and/or DOI, repository and licence if there is one (`[G]`).
2. **Claim** (one per line, numbered A1, A2...) decomposed: method or system, comparator, condition (model, dataset, split, metric, budget), direction of the effect, scope, certainty.
3. **Figure**: value, unit, where in the source (section, table, row, column); mark `checked` if re-read in the text, otherwise "copied, not re-read".
4. **Protocol**: number of runs or seeds, reported dispersion (standard deviation, CI) or "none", statistical test or "none", baselines present (model alone, random draw...), budget and its unit (calls, tokens, dollars), language or domain covered, cut-off date of the evaluated model if given.
5. **Link to code**: declared repository (HF `githubRepo`, CatalyzeX re-checked through the README), SHA or release if read, licence.
6. **Verified status**: `[A]` arXiv metadata, `[W]` open page, `[C]` Crossref, `[G]` GitHub, `[NV]` not verified; then the verifier's verdict per claim: `FOUND` / `DISTORTED` / `ABSENT` / `SOURCE-UNAVAILABLE` / `INVALID` / `UNVERIFIED`.
7. **Dates**: date of the source (all known ones) and T of the question; `before T` / `after T (excluded)`.

In the Methodology Appendix: receipt of the sources (consulted, accepted, rejected with reason, quotas reached), count of claims per verdict.

## Verification rules

Level 1 (`tools/verifier/ROLE.md`, the level-1 verifier role): every claim found in **its** source without distortion, element by element (figure, unit, comparator, condition, direction, scope, certainty, causality); proofs = fragments copied character for character, checked by `tools/verifier/citation_check.py` (a fragment that cannot be found invalidates the verdict); measured on our benches: 213/216 injected errors detected, 0/243 false alarms; with a second model family 72/72 and 0/81. Never as a collection filter.

In addition, specific to cs-ai:
1. **Citation check**: title, authors and year of every reference re-read on the arXiv API (`id_list`) or Crossref; a resolved identifier whose title differs is `DISTORTED`. An identifier that cannot be found is `[NV]` and the claim `ABSENT`.
2. **Venue**: `proceedings` only if read in Crossref or dblp; otherwise `announced`. Preprint and published version count once, the most recent first, both if their figures differ.
3. **Comparable figure**: a benchmark figure is `DISTORTED` if the card omits split, metric or budget when the source gives them; "state of the art" is admissible only when dated to the most recent work included.
4. **Protocol**: if the source reports neither multiple runs nor dispersion, the card says so plainly ("1 run, no error bars"); a superiority claim without a "model alone" or "random draw" baseline is marked `baseline missing`.
5. **Negative** ("nobody has done X"): requires a search receipt on arXiv and OpenAlex or Crossref (dblp too once wired) with the queries and the date bound.
6. **Date**: every source with a known date reaching T is excluded; the list of exclusions is attached to the receipt.
7. **Mechanical retraction check (rule shared by all plugins)**: for every retained DOI, the verifier reads Crossref `/works/<DOI>`: `has-update` then `update-to` (`update-type`: `retraction`, `erratum`, `expression_of_concern`), and cross-checks with Retraction Watch (CSV `crossref/retraction-watch-data`, distributed by Crossref); **no model call** (measured on our benches: 30/30 detected). State `retracted / erratum / concern / unknown` carried on the card; `unknown` is kept as is, never converted to `clean`. To be wired into `tools/verifier.py`; until then, Crossref read through the gateway (`read doi:<DOI>`).
8. **Code**: a repository is "official" only if HF declares it or if its README cites the paper; otherwise `community, unverified`.
