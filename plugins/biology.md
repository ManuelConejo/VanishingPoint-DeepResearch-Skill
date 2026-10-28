# Plugin biology - biomedicine and biology (2026-10-26)

Read by the engine (SKILL.md). Four fixed sections. Sources, format and verification filled by an agent from the dated gateway (measured on our benches: no leakage in 19/19 cases) and the authors' notes; the "Biases" section is to be completed by the owner. Every source says where its facts were established; "not established" = not established anywhere. Every key is optional.

## Sources

Block read by `tools/gateway.py` (format README.md); engines that are not wired are declared anyway and refused cleanly. Access marked according to `ACCESS-POLICY.md` (`api` level 1; `page` level 2, pacing 1 request / 2 s / host, declarative UA, cache, stop on 429/403; `browser` level 2b; `tos_forbidden`, `technical_block` level 3, listed and disabled). Probes dated 2026-10-26 unless stated.
```sources
engines: pubmed, europepmc, crossref, openalex, opencitations, gbif, ebi-search, unpaywall, clinicaltrials, doaj, biorxiv, medrxiv   # wired: pubmed, europepmc, crossref, openalex, clinicaltrials, biorxiv, medrxiv ; the others: not wired (unpaywall: already used downstream by tools/verifier/fetch_fulltext.py ; clinicaltrials: wired, option for a question on a specific trial or on publication bias ; biorxiv, medrxiv: wired, preprints dated per version, not peer reviewed ; doaj: option)
cap: 60                                  # safety cap on calls
keys: OPENALEX_KEY, NCBI_API_KEY         # optional, never required ; resolution KEYS.md (env NAME, ~/.config/vp/<name>.key) ; NCBI_API_KEY: 10 req/s instead of 3
useful_when: pubmed=large PubMed searches, systematic review, meta-analysis, many clinical trials ; openalex=broad searches outside MEDLINE, citation chaining, grey literature   # free-key sources ; read by tools/check_keys.py --suggest
access: pubmed=api, europepmc=api, crossref=api, openalex=api, opencitations=api, gbif=api, ebi-search=api, unpaywall=api, clinicaltrials=api, doaj=api, biorxiv=api, medrxiv=api   # ACCESS-POLICY.md
disabled: cochrane=browser, lilacs-scielo=browser, semantic-scholar=api, who-ictrp=technical_block, bhl=technical_block   # listed, not called ; reason under "Set aside"
```

Date bound: provider filter at the day before T, then local re-check: **every** known date < T, a partial date counts as its upper bound ("2025" = 2025-12-30) (gateway rule). The source review of a question is refused by DOI and by title (overlap >= 0.8). Chaining: Europe PMC first, OpenAlex as fallback; a reference without PMID passes only if its year is strictly earlier than that of T.

1. **PubMed (E-utilities)** - `access: api` (eutils robots `Disallow: /` has no effect on the documented API, level 1)
   - Endpoints: `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&retmode=json&sort=relevance&datetype=edat&mindate=1800/01/01&maxdate=<day before T, YYYY/MM/DD>&retmax=<n <= 50>&term=<query>`; `esummary.fcgi?db=pubmed&retmode=json&id=`; `efetch.fcgi?db=pubmed&id=&rettype=abstract&retmode=text`.
   - Query: PubMed syntax (MeSH, `[tiab]` fields, booleans); deep boolean enumeration then screening gave +13.79 points of total recall (measured on our benches); pagination at 200 records then cheap sorting.
   - Date bound: yes (`edat`), then re-check: Entrez date AND electronic publication date (or sort date) < T.
   - Key: OPTIONAL (`NCBI_API_KEY`, free NCBI account; sent as `api_key=` on every eutils request): official limit **3 req/s without key, 10 req/s with key** (ncbiinsights 2017). Rate: 0.45 s gateway, 0.11 s with the key.

2. **Europe PMC** (free full text, citing, references, bioRxiv **and medRxiv** preprints) - `access: api`
   - Endpoints: `https://www.ebi.ac.uk/europepmc/webservices/rest/search?format=json&resultType=lite|core&pageSize=<up to 100>&query=`; `/{src}/{id}/citations?format=json&pageSize=1000`; `/{src}/{id}/references?...`; `nextPageUrl` to paginate.
   - Query: Europe PMC syntax (`DOI:"..."`, `EXT_ID:... AND SRC:...`, `SRC:PPR AND PUBLISHER:"bioRxiv" AND (<words>)`; add **`PUBLISHER:"medRxiv"`** (90,891 records, probe 200) and `PUBLISHER:"Research Square"`; 32 preprint servers covered; `SRC:MED` = PubMed records, not to be duplicated).
   - Date bound: `firstIndexDate` AND `firstPublicationDate` < T (v1 tolerated the year: corrected after a poisoned test on our benches).
   - Key: none. Rate: 0.25 s gateway (1 s in the earlier prototype); published limit: not established. Free full text retrieved for 22 % of candidates (measured on our benches); outside MEDLINE (Agricola, patents, theses): 0 measured contribution.
   - VERIFY option: **Annotations API** `https://www.ebi.ac.uk/europepmc/annotations_api/annotationsByArticleIds?articleIds=MED:<pmid>&type=Gene_Proteins` (probe 200, no key): entities (genes, diseases, chemicals) extracted from the text with UniProt/ChEBI links, to tie a claim to an entity; `access: api`; not wired.

3. **Crossref** (resolve DOI, deposit and publication dates, retractions/errata) - `access: api`
   - Endpoint: `https://api.crossref.org/works?query.bibliographic=&rows=&select=DOI,title,issued,created,container-title,author,type&filter=until-created-date:<day before T>,until-pub-date:<day before T>&mailto=`; `/works/<DOI>`; batch `filter=doi:a,doi:b` (100).
   - Mechanical retractions, no LLM call: for every retained DOI `has-update:1` then read `update-to`; `filter=update-type:retraction` (76,441 notices, probe 200); **Retraction Watch** distributed by Crossref (GitLab CSV `crossref/retraction-watch-data`, daily; RW licence: not established). Rule shared by all plugins (see Verification).
   - Date bound: yes (`created` AND `issued`). Key: none. Rate: 0.25 s; published limit not established. Role: resolve, not search; coverage of the never-seen outside MEDLINE: 61/130 (measured on our benches).

4. **OpenAlex** - `access: api`
   - Endpoint: `https://api.openalex.org/works?per_page=&select=&filter=to_publication_date:<day before T>&search=`; `/works/doi:`, `/works/pmid:`; chaining by `openalex_id:a|b` (50 per call) as a fallback of Europe PMC.
   - Bound: `publication_date` < T then **mandatory Crossref re-check**; without a Crossref DOI, refused.
   - Key: OPTIONAL (`OPENALEX_KEY`: env or `~/.config/vp/openalex_key.key`, KEYS.md; never displayed); without key 0.10 USD/day, 429 -> Crossref fallback reported. Measured gain in biomedicine with key: +8 studies of 130 never seen, below the threshold. Rate: 0.2 s.

5. **OpenCitations** (citing, fallback) - `access: api`: `https://api.opencitations.net/index/v2/citations/doi:<DOI>`; key: none; rate 0.4 s gateway; published limit not established.

6. **Trial registries: ClinicalTrials.gov API v2** - `access: api` (robots `Disallow: /api/` has no effect, level 1); wired (engine `clinicaltrials`), **not retained by default**: called for a question on a specific trial or a publication-bias check (registered trials, including those never published)
   - Endpoint: `https://clinicaltrials.gov/api/v2/studies?query.term=<q>&filter.advanced=AREA[StudyFirstPostDate]RANGE[<a>,MAX]&pageSize=<up to 1000>&pageToken=`; probe 200 (630 for "cancer" since 2026-10-01); OpenAPI `clinicaltrials.gov/api/oas/v2` without `securitySchemes`.
   - Date bound: yes (`filter.advanced=AREA[StudyFirstPostDate]RANGE[MIN,<day before T>]`); local re-check: first submitted AND first posted < T; results served only when first posted < T (else `has_results: false`, results fields dropped); a record **updated on/after T** keeps id, title, conditions, sponsor and first dates, while status, phase, enrollment, start date, summary, outcomes and interventions are masked (`validity` says so); no date on/after T is ever served.
   - Key: none. Rate: not published -> local pacing 1 s. Measured contribution 8/243 before T (3.3 %), -2.01 points at equal length (measured on our benches): option for a question on a specific trial only.
   - State (2026-10-28): wired, `search-clinicaltrials "<q>"` (items `nct:<NCT id>`: title, status, phase, conditions, enrollment, has_results, dates) and `read nct:<NCT id>` (brief summary, primary/secondary outcomes, interventions, same barrier). Live probe: "semaglutide obesity" 10/10 at T 2026-10-26 (425 announced), 18 at T 2019-06-01, 0 date after T.

7. **Biological databases** (identity, sequence, structure, taxon; never a biological effect) - `access: api`
   - GBIF: `https://api.gbif.org/v1/literature/search?q=&offset=&limit=` (papers citing GBIF data); `https://api.gbif.org/v1/species/search?q=&datasetKey=d7dddbf4-2cf0-4f39-9b2a-bb099caae36c` (Backbone Taxonomy: accepted names and synonyms).
   - EBI Search: `https://www.ebi.ac.uk/ebisearch/ws/rest/{uniprot|ensembl_gene|pdbe}?query=&format=json&fields=&start=&size=` (Lucene; Ensembl's `species:` takes common names: a Latin name returned 0 results when probed on 2026-10-23).
   - Date bound: `creation_date` only (local re-check). Key: none. Rate: no published limit established; 1 s per host. Set aside at the probes of 2026-10-23: NCBI Gene/Taxonomy, Ensembl REST (identifiers only).
   - Same family, established options (all `access: api`, no key, not wired, identity or association only): **ChEMBL** `https://www.ebi.ac.uk/chembl/api/data/{molecule,...}.json` (probe 200, CC BY-SA 3.0, EBI robots Crawl-Delay 10); **UniProt REST** `https://rest.uniprot.org/uniprotkb/search?query=` with `date_created:[a TO *]`, CC BY 4.0; **RCSB PDB Search** `https://search.rcsb.org/rcsbsearch/v2/query?json=` with ISO dates, CC0, probe 200; **Ensembl REST** 55,000 req/h; **Open Targets** GraphQL POST `api.platform.opentargets.org/api/v4/graphql` (GET -> 500; not probed in POST; CC0); **Reactome** `https://reactome.org/ContentService/search/query?query=` (probe 200, CC0); **PubChem PUG REST** `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/<name>/cids/JSON` (probe 200; rate: not established, page behind reCAPTCHA); **openFDA** (without key 240/min and 1,000/day, free key 120,000/day; pharmacovigilance).

8. **Unpaywall** (location of the free full text; already used downstream by `tools/verifier/fetch_fulltext.py`) - `access: api`; declared here, not wired in the gateway
   - Endpoint: Unpaywall API by DOI, `email=` mandatory (422 otherwise; VP_CONTACT); probe 200.
   - Key: none. Rate: 100,000/day (excerpt, JS page).

9. **DOAJ** (open-access journals not indexed in MEDLINE, global south) - `access: api`; option, contribution to measure (LILACS/SciELO 403; DOAJ is the open route to those journals)
   - Endpoint: `https://doaj.org/api/search/articles/<q>` (probe 200, 23,251); metadata CC0.
   - Date bound: date fields not established -> local re-check only. Key: none. Rate: 2 req/s.

10. **Preprints: bioRxiv and medRxiv** (engines `biorxiv`, `medrxiv`) - `access: api` (Europe PMC REST and `api.biorxiv.org`, level 1; `www.biorxiv.org` is never called: its robots.txt disallows AI crawlers, and the gateway has no need of it)
   - Route: `api.biorxiv.org` has **no keyword search** (`details/<server>/<interval|DOI>`, `pubs/...`; probe 200, 2026-10-28), so the words go to Europe PMC `search?query=(<q>) AND SRC:PPR AND PUBLISHER:"bioRxiv"` (or `"medRxiv"`), then each hit is dated on `https://api.biorxiv.org/details/<server>/<DOI>/na/json` (one row per version: date, title, abstract, `published`). Preprint DOIs: `10.1101/...` and, for new posts, `10.64898/...` (openRxiv prefix, measured 2026-10-28).
   - Date bound: provider side `FIRST_PDATE:[<start> TO <day before T>] AND FIRST_IDATE:[<start> TO <day before T>]`; local re-check: **version 1 posted < T** AND Europe PMC first publication and indexing < T; no date -> refused. Served: title, authors, category, licence and abstract of the **latest version posted < T**; later versions are never read (`later_versions_masked: true`). The published-article DOI is checked against the forbidden list at any date, and shown (`published_doi`, journal, year) only when Crossref attests its deposit AND publication < T; otherwise nothing is said. Forbidden titles checked on every version and on the Europe PMC title.
   - Reading: `read biorxiv:<DOI>`, `read medrxiv:<DOI>`, and `read doi:<preprint DOI>` (routed here: the Europe PMC core record carries the latest version, possibly after T); `citing` / `references` of a preprint pass only when its v1 is before T.
   - Key: none. Terms: no terms nor limit on the API page; bioRxiv FAQ (read 2026-10-28): "free and unrestricted access ... also to machine analysis". Rate: 1 req/s local on `api.biorxiv.org` (one call per hit), stop on 403/429; a failing host stops the call (hits reported not datable, never an empty result).
   - Caveat: **preprint, not peer reviewed** (`peer_review` field; see the preprint bias below); prefer the published version when it is shown. Recall depends on Europe PMC's preprint index (relevance on its current record).
   - State (2026-10-28): wired, `search-biorxiv "<q>"`, `search-medrxiv "<q>"` (items `doi:<preprint DOI>`, server, date (v1), date_version, version, later_versions_masked, published_doi) and `read biorxiv:<DOI>` / `medrxiv:<DOI>`. Live probe "SARS-CoV-2 spike antibody": bioRxiv 20/20 at T 2026-10-26 (4,027 announced) and 20/20 at T 2020-06-01 (296; 3 later versions masked, 3 published links shown, 1 published after T hidden), medRxiv 20/20 at T 2020-06-01 (148); 0 date on/after T.

Other options: **bioRxiv/medRxiv API** `https://api.biorxiv.org/details/{server}/{YYYY-MM-DD/YYYY-MM-DD}/{cursor}/json` (by interval, DOI, `category`; **no keyword**; probe 200) `access: api`: wired to date versions (engines `biorxiv`, `medrxiv`, section 10), never to search; **OpenAIRE Graph** (60 req/h without token) `api`; **PMC OAI-PMH / BioC** `https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/?verb=...&set=pmc-open` (`from`/`until`), BioC JSON by PMID/PMCID, 3 req/s; OA web service discontinued (`pmcid` support planned) `api`; **Semantic Scholar** with key (see `cs-ai.md`, Sources 5) `api`.

Set aside: **Cochrane Library / CENTRAL** (403 on robots.txt and help pages, no public API, TDM under Wiley terms; `access: browser`, disabled as long as the browser mode is not wired; Cochrane reviews have DOIs 10.1002/14651858 resolvable through Crossref/PubMed); **LILACS/SciELO** (403; `browser`, disabled); **WHO ICTRP** (web service on request, possible cost; `technical_block`); **EU CTR / CTIS** (no API); **PROSPERO** (no API nor export); **NIH RePORTER** (funding, not a source of claims); **BHL** (key required, 401; `technical_block`); **Lens, Dimensions, Scopus** (key or institution; `technical_block`); **CORE** (quota); translated queries (0 contribution, measured on our benches).

## Discipline biases

Feynman form (one signal per line, the observable trigger, never a verdict). Shared catalogue: `vp-bias-catalogue/1`, discipline file `biomedical` (`usage = "signal"`, 16 biases `bio.*`, 22 references: the 5 domains of RoB 2, ROBINS-I, QUADAS-2, GRADE, analytical flexibility, spin, funding). **Not measured against the catalogue set** (only finance and AI were); grid outside the product by default. Catalogue ids, to flag when the text of the source triggers them: `bio.randomisation`, `bio.deviations`, `bio.missing_outcome`, `bio.outcome_measurement`, `bio.selective_reporting`, `bio.confounding`, `bio.selection_immortal_time`, `bio.misclassification`, `bio.diagnostic_spectrum`, `bio.publication_bias`, `bio.imprecision`, `bio.inconsistency`, `bio.indirectness`, `bio.flexible_analysis`, `bio.spin`, `bio.sponsorship`. Biases already documented:
- **Source review and temporal leakage**: the review that asks the question, its citing papers and any document dated >= T are excluded by DOI, title and dates (gateway rule; a poisoned test of v1 on the partial year).
- **Retraction, erratum, expression of concern** not flagged by the indexes: measured on our benches, 11 retracted, 169 errata in the outputs so far; 1 retracted in a top 25.
- **Model memory** taken for a search: memory-only probe 34.4 % recall (measured on our benches); every result must have a query receipt.
- **Truncation and length**: 34.2 % of the studies of an answer key are seen by no run, first by truncation at 20 records (measured on our benches); a recall gain through length is not a method gain.
- **Outside MEDLINE, language, grey literature**: 25.9 %, 15.2 %, 9.9 % of the never-seen (measured on our benches); out of reach without a key, to be announced as coverage, not as absence.
- **Preprint != peer-reviewed**: primary but not reviewed; prefer the published version when it exists (engines `biorxiv`, `medrxiv`: `published_doi` shown only when published before T).
- **Organism and system** (`bio.indirectness`): a result on another organism, in vitro, or in silico is indirect evidence; a database entry supports an identity, never an effect.
- **Weak eligibility judge**: a cheap judge loses (measured on our benches); judging the whole pool does not pay.
- General Feynman grid, applicable to observational studies and trials: multiple tests and subgroups chosen after the fact (`bio.flexible_analysis`, `bio.selective_reporting`), survivors and immortal time (`bio.selection_immortal_time`), period, replicability (data, code, pre-registration), spin (`bio.spin`), funding (`bio.sponsorship`): **not measured in biology**.
- To be completed by the owner.

## Output format

One **study card** per reference (the `card.json` schema checked by `tools/validate_card.py`; `required_context` of the biology prototype):
1. **Full citation**: authors, title, year, journal or preprint server, DOI, PMID / PMCID, type (`trial`, `observational`, `systematic review`, `preprint`, `database entry`).
2. **Claim** (A1, A2...) decomposed: population or **organism (species, strain, population)**, intervention or exposure, comparator, **experimental system (in vivo, in vitro, field, in silico)**, figure and unit, direction, certainty (significant or not), scope (subgroup or whole), causality (association or effect).
3. **Figure**: value, unit, CI or p, n, where in the source; `checked` if re-read.
4. **Protocol**: study design, duration, pre-registration or registry, funding if read.
5. **Accessions** cited (UniProt, Ensembl, PDB, GBIF key) with their database; accepted name of the taxon (synonym resolved by the Backbone).
6. **Verified status**: `[P]` PubMed, `[E]` Europe PMC, `[C]` Crossref, `[O]` OpenAlex, `[NV]`; state `retracted / erratum / concern / unknown`; level-1 verdict per claim.
7. **Dates**: `firstPublicationDate`, `created`, `issued`, Entrez date; T; `before T` / `excluded`.

At the end of the report: two-tier output (main, extended); receipt of the sources (queries, number of records, truncations, quotas); exclusions by date and by source review.

## Verification rules

Level 1 (`tools/verifier/ROLE.md`, the level-1 verifier role; measured on our benches: 213/216 injected errors detected, 0/243 false alarms; with a second model family 72/72) with fragments checked by `tools/verifier/citation_check.py`. Never as a collection filter (measured on our benches: recall 48.5 -> 29.8 %).

In addition, specific to biology:
1. **Population and organism**: a claim whose organism, strain, experimental system or subgroup differs from the source is `DISTORTED`; a cross-species transfer not stated by the source is `ABSENT`.
2. **Certainty and causality**: "significant", "effect" and "cause" are `FOUND` only if the source says so; association != effect.
3. **Mechanical retraction check (rule shared by all plugins)**: for every retained DOI, the verifier reads Crossref `/works/<DOI>`: `has-update` then `update-to` (`update-type`: `retraction`, `erratum`, `expression_of_concern`), and cross-checks with Retraction Watch (CSV `crossref/retraction-watch-data`); **no model call** (measured on our benches: 30/30 detected). State `retracted / erratum / concern / unknown` on the card; `unknown` stays `unknown`. To be wired into `tools/verifier.py`; until then, Crossref read through the gateway (`read doi:<DOI>`).
4. **Dates**: Entrez date AND electronic publication (PubMed), `firstIndexDate` AND `firstPublicationDate` (Europe PMC), `created` AND `issued` (Crossref) < T; otherwise excluded and listed.
5. **Source review**: forbidden DOI and title (overlap >= 0.8) refused, including under another DOI.
6. **Accession**: must resolve in its database (UniProt, Ensembl, PDBe, GBIF); an accession that does not resolve makes the claim `SOURCE-UNAVAILABLE`.
7. **Disordered PDF**: fragments copied from a PDF text concentrate the rejections (measured on our benches); copy from the Grep output, tables rebuilt row and column.
8. **Negative** ("no study"): receipt of PubMed and Europe PMC queries with bounds, otherwise `ABSENT`.
