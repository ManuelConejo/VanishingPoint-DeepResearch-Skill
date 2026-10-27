# Plugin finance - finance and economics (2026-10-26)

Read by the engine (SKILL.md). Four fixed sections. Sources, format and verification filled by an agent from the dated gateway and the authors' notes; the "Biases" section is to be completed by the owner. Every source says where its facts were established; "not established" = not established anywhere. Every key is optional: without a key, the source is skipped with a receipt `credential_missing`, never "nothing found".

## Sources

Block read by `tools/gateway.py` (format README.md); engines that are not wired are declared anyway and refused cleanly. Access marked according to `ACCESS-POLICY.md` (`api` level 1; `page` level 2, pacing 1 request / 2 s / host, declarative UA, cache, stop on 429/403; `browser` level 2b; `tos_forbidden`, `technical_block` level 3, listed and disabled). Probes dated 2026-10-26 unless stated.
```sources
engines: econbiz, openalex, crossref, europepmc, arxiv, edgar, fred, dbnomics, ecb, eurostat, worldbank, worldbank-wds, imf, oecd, bis, insee-bdm   # wired: openalex, crossref, europepmc, arxiv (econ.*, q-fin.*) ; the others: not wired (dbnomics...insee-bdm: shared SDMX adapter planned)
cap: 60                                  # safety cap on calls
keys: OPENALEX_KEY, FRED_API_KEY         # optional ; FRED without key = disabled, no call
useful_when: fred=US macroeconomic series, rates, inflation, GDP, unemployment, point-in-time values, data revisions, ALFRED ; openalex=broad searches, working papers, citation chaining   # free-key sources ; read by tools/check_keys.py --suggest
access: econbiz=api, openalex=api, crossref=api, europepmc=api, arxiv=api, edgar=api, fred=api, dbnomics=page, ecb=api, eurostat=api, worldbank=api, worldbank-wds=api, imf=api, oecd=api, bis=api, insee-bdm=api   # ACCESS-POLICY.md (DBnomics: named example of level 2, rate not published -> level-2 pacing)
disabled: ssrn=tos_forbidden, yahoo=tos_forbidden, repec-ideas=technical_block, cepr=technical_block, econlit=technical_block, scopus=technical_block, xbrl-us=technical_block   # listed, not called ; reason under "Set aside"
```

Date bound: the day before T on the provider side, then local re-check of every known date < T (gateway rule).

1. **EconBiz** (ZBW: articles, working papers, books; the key-less route, because RePEc/IDEAS and SSRN have no public search API) - `access: api`
   - Endpoint: `https://api.econbiz.de/v1/search` (JSON `hits.hits[*]`, total `hits.total`).
   - Query: `q=<text>` with `AND/OR/NOT`, quoted phrases, fields `title:`, `subject:`, `person:`; STW vocabulary (economics thesaurus) and JEL codes as subjects; pagination `from=`, `size=` (100 per page, 300 max).
   - Date bound: no established provider filter; local re-check on `date[0]`.
   - Key: none. Rate: published limit not established; 1 s local. Measured: 30 records with a full receipt in a real trial without key.

2. **OpenAlex, field 20 "Economics, Econometrics and Finance"** - `access: api`
   - Endpoint: `https://api.openalex.org/works`; resolution `/works/doi:<DOI>`.
   - Query: `search=<text>`, `filter=primary_topic.field.id:20,to_publication_date:<day before T>`, `select=id,doi,display_name,publication_year,publication_date,primary_location,authorships,type`, `per_page <= 50`; subfield 2003 = Finance. **SSRN working papers without touching SSRN**: filter `locations.source.id:<OpenAlex id of the SSRN source>` (trick seen in the open-source `openags/paper-search-mcp`, `ap/ssrn.py`; id of the source: not established here, to be recorded at the first call `/sources?search=SSRN`); `access: api`.
   - Date bound: yes, then mandatory Crossref re-check (deposit AND publication < T); without a Crossref DOI, refused.
   - Key: OPTIONAL (`OPENALEX_KEY`: env or `~/.config/vp/openalex_key.key`, KEYS.md; never displayed); without key 0.10 USD/day shared per IP, 429 possible from the 1st call -> receipt `rate_limited`, Crossref fallback reported. Rate: 0.2 s gateway.

3. **Crossref** (resolve DOI, dates, published version of a working paper, retractions; **NBER and SSRN by prefix**) - `access: api`
   - Endpoint: `https://api.crossref.org/works?query.bibliographic=&rows=&select=DOI,title,issued,created,container-title,author,type&filter=until-created-date:<day before T>,until-pub-date:<day before T>&mailto=`; `/works/<DOI>`.
   - **NBER Working Papers**: `filter=prefix:10.3386` + `query.bibliographic=` isolates the series (Crossref member 1960); dates and resolution through Crossref; watch through RSS `https://back.nber.org/rss/new.xml` (+ per programme, probe 200; `access: page`); data.nber.org blocks robots: do not go there. **SSRN** working papers with DOI 10.2139 remain resolvable here without touching SSRN.
   - Mechanical retractions: `has-update:1` then `update-to`; `filter=update-type:retraction`; Retraction Watch (CSV `crossref/retraction-watch-data`). Shared rule (Verification).
   - Date bound: yes (`created` AND `issued`). Key: none. Rate: 0.25 s gateway; published limit not established. Role: resolve, not search.

4. **Europe PMC** - `access: api`: biomedical; for finance, only health economics. Endpoint and bounds: see `biology.md`, Sources 2. Key: none.

5. **arXiv, categories econ.EM/GN/TH and q-fin.CP/EC/GN/MF/PM/PR/RM/ST/TR** (economics and quantitative finance preprints; engine already wired, declared here at zero cost; taxonomy arxiv.org/category_taxonomy) - `access: api`
   - Endpoint: `https://export.arxiv.org/api/query`; `search_query=cat:q-fin.* OR cat:econ.*` combined with keywords (`ti:`, `abs:`), `max_results <= 100`.
   - Date bound: yes, `submittedDate:[... TO <day before T>2359]`; local re-check on `published`. Key: none. Rate: 3 s. Detail: `cs-ai.md`, Sources 3.

6. **EDGAR / XBRL (SEC)** - **primary** source of US company figures, mechanical verification without LLM - `access: api`
   - Endpoints: `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` (source of the verifier; 404 XML `NoSuchKey` without XBRL); `https://data.sec.gov/api/xbrl/frames/us-gaap/<Tag>/<Unit>/CY2024[Qn][I].json` (cross-section, no pagination); `https://efts.sec.gov/LATEST/search-index?q="..."&forms=&ciks=&dateRange=custom&startdt=&enddt=&from=` (full text of filings, 100 per page); `company_tickers.json` for the CIKs; **`https://data.sec.gov/submissions/CIK##########.json`** (list of a company's filings, probe 200, 164 KB; same adapter); nightly zips `submissions.zip`, `companyfacts.zip` and quarterly **Financial Statement Data Sets** `sec.gov/files/dera/data/financial-statement-data-sets/YYYYqN.zip` (2009q1 -> 2026q3): offline option.
   - Query: by CIK and us-gaap tag; the period is read on `start/end`, **never on `fy`** (fiscal year of the filing). Beyond 10,000 results `efts` answers **HTTP 200 with `errorType: ResponseError`**: to be typed `bounded`, never "empty".
   - Date bound: yes (`startdt`/`enddt` for efts; `end` and filing date for XBRL; `filingDate` in `submissions`).
   - Key: none; **declarative User-Agent mandatory** (name + contact, VP_CONTACT; without it, 403 everywhere). Rate: SEC cap 10 req/s; prototype at 4 req/s without 429.
   - Measured on our benches (72 true + 288 mutations, 59 companies): 0/72 false alarms, 288/288 mutations detected; limit: rounding (+/- 0.2 % invisible in 48 to 51 of 57 cases); partial circularity (frames and companyfacts = same XBRL base).

7. **FRED / ALFRED (St. Louis Fed)** - macro series, values "as known at a date" (point-in-time) - `access: api` (key required by the service, free)
   - Endpoint: FRED API; ALFRED via `realtime_start = realtime_end = <date>`. Exact URL: not established here (built and tested in an earlier prototype, not wired).
   - Key: OPTIONAL but required by the service (`FRED_API_KEY`, free); without key: status `disabled`, receipt `credential_missing`, no network call (tested; the API without key returns HTTP 400). Rate: not established. Fallback without key: the primary sources 9-15 below.

8. **DBnomics** (aggregator: IMF, OECD, Eurostat, ECB, INSEE, BIS, World Bank...; 47,421 datasets, 1.7 G series; **the only full-text search** over series, the native SDMX APIs have none) - `access: page` (named example of level 2 in ACCESS-POLICY.md: robots `Disallow: /` on the API host, rate not published -> pacing 1 request / 2 s, declarative UA, cache)
   - Endpoints: `https://api.db.nomics.world/v22/search?q=<text>` and `/providers` (probe 200); series by `provider/dataset/series`.
   - Date bound: by observation period (local re-check). Key: none. Licence: ODbL, data = licence of the original provider. Rate and precise terms: not established.

9. **ECB Data Portal** (rates, exchange rates, euro-area aggregates; European primary source) - `access: api`
   - Endpoint: SDMX 2.1 `https://data-api.ecb.europa.eu/service/data/{flow}/{key}?startPeriod=&endPeriod=` (probe 200, CSV).
   - Date bound: yes (`startPeriod`/`endPeriod`). Key: none. Rate and licence: not established -> 1 s local.

10. **Eurostat** (official EU statistics) - `access: api`
    - Endpoint: `https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{code}` (JSON-stat), `sinceTimePeriod=`/`untilTimePeriod=` (probe 200).
    - Date bound: yes. Key: none. Reuse with source attribution (CC BY 4.0 editorial). Rate: not established -> 1 s local.

11. **World Bank - Indicators and Documents & Reports (WDS)** (macro, 200 countries; **dated grey literature**: Policy Research Working Papers) - `access: api`
    - Endpoints: `https://api.worldbank.org/v2/country/{iso}/indicator/{code}?date=<a>:<b>&format=json` ("API keys no longer necessary"); documents: `https://search.worldbank.org/api/v3/wds?qterm=<q>&strdate=&enddate=&format=json` (probe 200: 24,604 documents for "inflation").
    - Date bound: yes (`date=a:b`; `strdate`/`enddate`). Key: none. Terms: no commercial use without agreement; datasets CC BY 4.0. Rate: not established -> 1 s local.

12. **IMF, SDMX 3.0 (2025)** (WEO, IFS, balance of payments) - `access: api`
    - Endpoint: `https://api.imf.org/external/sdmx/3.0/...` (probe 200); the old `dataservices.imf.org` has **disappeared (NXDOMAIN)**.
    - Date bound: by SDMX period. Key: none. Terms: not established. Rate: not established -> 1 s local.

13. **OECD (SDMX)** (OECD indicators) - `access: api`
    - Endpoint: `https://sdmx.oecd.org/public/rest/data/{flow}/{key}?startPeriod=` (v1); v2: `c[TIME_PERIOD]`, `updatedAfter` (probe 200). The URL `data.oecd.org/api` proposed by a reviewer is **wrong**.
    - Date bound: yes. Key: none. Licence: not established (terms page 403). Rate: not established -> 1 s local.

14. **BIS** (cross-border credit, debt, property prices, monetary policy) - `access: api`
    - Endpoint: `https://stats.bis.org/api/v2/data/dataflow/BIS/{flow}/{ver}/{key}?startPeriod=` (probe 200).
    - Date bound: yes. Key: none. Use "unrestricted" with citation; IP cut-off possible -> 1 s pacing, stop on 429/403.

15. **INSEE BDM** (French series) - `access: api`
    - Endpoint: SDMX BDM (probe 200; doc `insee.fr/fr/information/8184146`); exact path: not established (to be recorded when wired). The other INSEE APIs (Sirene...) need a key: option.
    - Date bound: by SDMX period. Key: none (BDM). Licence: not established. Rate: not established -> 1 s local.

Planned wiring: a **single SDMX adapter** for 9, 12, 13, 14, 15.

Options (not declared): **Banque de France Webstat** (key, account, 10,000 calls/day, 401 without key) `api`; **GLEIF LEI** `https://api.gleif.org/api/v1/lei-records?filter[entity.legalName]=` (probe 200, JSON:API, group structures; rate and licence not established; identity, not a source of claims) `api`; **BLS API v2** (without key 25 req/day, free key 500/day, `startyear`/`endyear`; FRED covers) `api`; **BEA** (key, 100 req/min), **Fed DDP** (without key, SDMX per publication), **FRASER** (key on request, 30/min, OAI-PMH); **UK Companies House** (key, 600 req / 5 min) `api`; **CitEc** `citec.repec.org/api/{plain|amf|citedby}/<handle>` (without key up to 500 requests, probe 200; `citing` of a RePEc handle already known; commercial use excluded) `api`; **Alpha Vantage, Finnhub** (key required; AV 25 req/day free; option if a question requires a price, never default) `api`; **Stooq** (robots `Disallow: /` only, never probed) `page`, option never default; **OpenBB** = Apache-2.0 Python aggregator, not a source (its key-less extensions overlap 9-15).

Set aside, disabled: **SSRN** (no API, 403 Cloudflare, **Elsevier terms forbid any automation and use with an AI tool**; `access: tos_forbidden`; exception only by a written decision of the owner in ACCESS-POLICY.md; DOI 10.2139 through Crossref); **Yahoo Finance** (terms forbid any automated access, robots `Disallow: /`; `tos_forbidden`); **RePEc / IDEAS / EconPapers** (API "not openly available", no search; OAI 502; dumps on request; `technical_block` for search); **CEPR DP** (403 Cloudflare, PDF on subscription: paywall; metadata through RePEc; `technical_block`); **EconLit** (EBSCO subscription) and **Scopus** (key + institutional right) `technical_block`; **XBRL US** (account, strictly non-commercial; companyfacts covers) `technical_block`; **OpenFIGI** (outside the documentary need); Exa, Perplexity (third-party model or key: option, never default).

## Discipline biases

Feynman form (measured on our benches, drawn from the owner's real use: a 6-axis audit wrapper, 162 audit sessions of quantitative finance papers). Shared catalogue: `vp-bias-catalogue/1`, discipline file `finance` (`usage = "signal"`, 16 biases `fin.*`, 28 verified references; it takes the owner's grid and widens it). Measurement of the catalogue (measured on our benches on 14 finance papers, two model families): apparent recall 8-10/10 but **3-4/10** with the only citation verified in the text (39 detections of 55 came from memory); raw precision 0.31; `fin.vol_targeting` (4/4 with citation, 0 alert on the control) is the only candidate to re-measure. These are **signals, not verdicts**; on a fresh set no judge reaches the threshold, grid outside the product by default.
- **Data leakage (look-ahead)** (`fin.look_ahead`): information used before it was known; revised data taken for point-in-time data (hence ALFRED).
- **Point-in-time data** (`fin.point_in_time`): universe, fundamentals and indexes as they existed at the date, not retrospective; **backfill and self-selection** of voluntary databases (`fin.backfill_selection`).
- **Specification search, multiple testing (p-hacking)** (`fin.data_snooping`, `fin.multiple_testing`, `fin.p_hacking`): number of variants tried not declared; thresholds chosen after the fact; significance threshold too low for the number of tests.
- **Inflated Sharpe** (`fin.backtest_overfitting`: Sharpe not deflated; `fin.sharpe_inflation`: smoothing, wrong annualisation; `fin.vol_targeting`: volatility targeting with an in-sample scale; `fin.transaction_costs`: returns gross of costs): volatility targeting, returns gross of transaction and financing costs, survivorship bias in the universe.
- **Survivorship bias** (`fin.survivorship`): defunct companies or funds absent from the sample.
- **Period** (`fin.sample_period`): too short, or limited to crises; result outside the period or the market = indirect evidence only. **No out-of-sample or post-publication evidence** (`fin.no_out_of_sample`): weakly specific signal (triggers on the controls).
- **Replicability** (`fin.replicability`): code and parameters absent, data errors; published version and working paper whose figures differ (keep both).
- **Universe** (`fin.microcap_weighting`): small caps or all caps, equal weighting, thresholds on all stocks; market and frequency to note for each candidate.
- **Endogeneity** (`fin.endogeneity`): omitted variables, reverse causality, invalid instruments; in the catalogue, not observed in our own sets.
- **Second-hand figure**: a figure that appears only in a news item, a blog post or a slide is grey literature; the same figure read in XBRL is verified mechanically.
- **Verdict read in the prompt echo**: false PASS observed in the owner's wrapper (measured on our benches); verdicts stay typed, never drawn from a substring.
- To be completed by the owner.

## Output format

One **study card** per reference (common format: the `card.json` schema checked by `tools/validate_card.py`), with the finance-specific fields (`required_context`):
1. **Full citation**: authors, title, year, venue (`journal` / `working paper: NBER, central bank, SSRN-hosted` / `preprint`), DOI or identifier, version (working paper and published if the figures differ).
2. **Claim** (A1, A2...) decomposed: effect or anomaly or model, comparator, direction, scope, certainty.
3. **Figure**: value, **unit**, **period (start, end)**, **market or universe**, **frequency**, **data source** (CRSP, Compustat, Bloomberg, central bank series, XBRL...), where in the source; `checked` if re-read.
4. **Protocol**: in-sample / out-of-sample / post-publication; costs included or not; number of specifications tried if declared; code and parameters available.
5. **Flagged biases**: lines of the "Biases" section that apply, with the element of the source that triggers the signal (never a verdict).
6. **Verified status**: `[C]` Crossref, `[W]` open page, `[X]` figure confirmed by XBRL (value, unit, period, form in the same record), `[NV]`; level-1 verdict per claim.
7. **Dates**: dates of the source and T; `before T` / `excluded`.

At the end of the report: provenance receipt (sources consulted, accepted, rejected with reason, quotas, duplicates); measured on our benches on 40 outputs, 9 % of the rejections had no written reason and 18 sources were later than T: these two counts are mandatory.

## Verification rules

Level 1 (`tools/verifier/ROLE.md`, the level-1 verifier role; fragments checked by `tools/verifier/citation_check.py`), plus:
1. **`figure_period_source`**: a figure without value, unit, period and data source in the **same passage** is `unsupported`; a figure with a period or market different from the question is `indirect evidence`, not direct.
2. **US company figure**: mechanical verification against `companyfacts` (CIK, tag, unit, `start/end`, form) before any LLM judgement; `fy` is never read as a period. A gap within the rounding tolerance is flagged as such (measured limit).
3. **Point-in-time**: a claim "value known at date D" is `FOUND` only if the source gives the vintage (ALFRED, or the dated filing); otherwise `DISTORTED: revised value`.
4. **Working paper -> published**: Crossref resolution; if the figures differ, the card carries both and the verdict is made on the cited version.
5. **Mechanical retraction check (rule shared by all plugins)**: for every retained DOI (including NBER 10.3386 and SSRN 10.2139), the verifier reads Crossref `/works/<DOI>`: `has-update` then `update-to` (`update-type`: `retraction`, `erratum`, `expression_of_concern`), and cross-checks with Retraction Watch (CSV `crossref/retraction-watch-data`); **no model call** (measured on our benches: 30/30 detected). `unknown` stays `unknown`. To be wired into `tools/verifier.py`; until then, Crossref read through the gateway (`read doi:<DOI>`).
6. **Date**: every source with a known date reaching T is excluded and listed.
7. **Typed verdict**: verdicts come out as typed JSON, never read from free text.
