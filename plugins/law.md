# Plugin law - France and Europe (2026-10-26)

Read by the engine (SKILL.md). Four fixed sections. Sources probed for real on our benches on 2026-10-22 (endpoints, options with key, coded rules, observed discrepancies) and an earlier prototype whose endpoints it takes over; bias catalogue: discipline file `law` (7 defects). "Not established" = not established anywhere. Every key is optional: a source with key and no credential makes zero request and returns `not_configured` / `credential_missing`, never "nothing found"; a route made only of key sources is refused. US law (CourtListener) is set aside (a possible future US plugin).

## Sources

Block read by `tools/gateway.py` (format README.md); only `openalex` is wired on day 1, the other engines are listed `not_wired` and refused cleanly. Legifrance and the Conseil constitutionnel are not declared: not queryable for search (see 6 and 9). Access marked according to `ACCESS-POLICY.md` (`api` level 1; `page` level 2, pacing 1 request / 2 s / host, declarative UA, cache, stop on 429/403; `browser` level 2b, driven browser on a public page behind a JS challenge; `tos_forbidden`, `technical_block` level 3, listed and disabled). Probes dated 2026-10-26 unless stated.
```sources
engines: eurlex, hudoc, justice-administrative, judilibre, hal, openalex, europarl, isidore, theses-fr   # wired: openalex ; the others: not wired (europarl, isidore, theses-fr: planned ; hudoc: re-probe planned)
cap: 60                                  # safety cap on calls
keys: OPENALEX_KEY, PISTE_CLIENT_ID, PISTE_CLIENT_SECRET   # optional ; without a PISTE token, judilibre = not_configured, 0 request
useful_when: judilibre=French judicial case law, Cour de cassation, rulings, appeal, civil commercial social criminal chambers ; openalex=doctrine, legal articles, journals, citation chaining   # free-key sources ; read by tools/check_keys.py --suggest
access: eurlex=api, hudoc=page, justice-administrative=page, judilibre=api, hal=api, openalex=api, europarl=api, isidore=api, theses-fr=api   # ACCESS-POLICY.md ; hudoc and justice-administrative: undocumented endpoints -> level-2 regime ; hudoc: browser fallback on JS challenge
disabled: legifrance-html=browser, conseil-constitutionnel-recherche=page, curia=page, juricaf=page, openedition-persee=page, bofip-api=page, conseil-ue=browser, doctrine-dalloz-lexis=technical_block, bailii=tos_forbidden   # listed, not called until wired ; reason in the text
```
Audit mode (SKILL.md, section "Audit mode") is recommended for this plugin: exhaustive verification of every atomic claim before any binding legal conclusion; set VP_MODE=audit or ~/.config/vp/mode.

Route order: EU texts and rulings, EU preparatory works, ECHR, administrative courts, Cour de cassation (if token), then doctrine (Isidore, HAL, theses.fr, OpenAlex). Every record carries its **tier** (`primary` / `secondary` / `grey`), its **legal order** (`EU`, `COE`, `FR-ADM`, `FR-JUD`) and, where relevant, its coverage start date. Date bound: the question carries a date; the rule `in_force_at_date` (see Verification) replaces the "day before T" filter of the other plugins, and the gateway refuses the source document and anything later than it (test cases only).

1. **EUR-Lex, Cellar SPARQL - legislation** (`eurlex_legislation`, primary, `EU`) - `access: api`
   - Endpoint: `https://publications.europa.eu/webapi/rdf/sparql` (GET, JSON SPARQL).
   - Query: SPARQL template on the title; fields returned: CELEX, entry into force (`in_force_from`), application (`applies_from`), end of validity (`in_force_to`, **inclusive**), "in force" flag, "declares void" links (`declares_void` and `declares_void_by_preliminary_ruling`, both read); `LIMIT/OFFSET` 100, 300 max, 3 pages. Records grouped **by CELEX**; `_RES` and `_INF` records set aside.
   - Measured traps: an `OPTIONAL` on the ELI returned in HTTP 200 the dates of another act (directive 95/46 with the dates of decision 2021/701); `IF(COUNT())` and `SUBSTR(SAMPLE())` give HTTP 500 "VECSL internal error" = `provider_error`, not empty; citation metadata `work_cites_work` empty for the rulings of July-October 2026 (several months' delay).
   - Date bound: through the validity dates (rule). Key: none. Rate: 2 s local; published limit: not established. Probed for real on 2026-10-22: 200. Option: **EUR-Lex SOAP web service** (free registration, daily cap stated at registration, WSDL 200; does not download the documents) `access: api`, not built.

2. **EUR-Lex, Cellar SPARQL - CJEU case law** (`eurlex_caselaw`, primary, `EU`) - `access: api`
   - Same endpoint and same limits. Fields: CELEX, ECLI, court (`CJ`, `CO` = orders of the Court, `T` = General Court), `set_aside_by` (appeal, preliminary ruling). Cellar twins: the same ruling (T-286/09) exists as two works and the annulment link is attached to only one -> grouping by CELEX mandatory.
   - Excluded: the opinions of the Advocates General (CELEX `...CC...`), non-binding (`law.non_binding`).
   - Completeness of opinions (`CC`) and orders (`CO`) in Cellar: **not established**. Fallback if it proves incomplete: **CURIA / InfoCuria** read as HTML by case number (`infocuria.curia.europa.eu`, robots `Allow: /`, no API, RSS removed) `access: page`, option not wired.

3. **HUDOC (ECHR)** (`hudoc`, primary, `COE`) - `access: page` (endpoint not documented by the Court; `/robots.txt` returns the SPA, no robots); `browser` fallback on JS challenge
   - Endpoint: `https://hudoc.echr.coe.int/app/query/results?query=contentsitename:ECHR AND (languageisocode:"FRE" OR "ENG") AND (doctype HEJUD|HFJUD|HEDEC|HFDEC) AND (<q>)&select=itemid,docname,appno,kpdate,doctype,importance,respondent,conclusion,ecli,...&sort=kpdate Descending&start=&length=50`.
   - State: on 2026-10-22, 403 Cloudflare challenge from this server; **on 2026-10-26, 200 JSON** with a declarative User-Agent on `.../app/query/results?query=contentsitename:ECHR&select=itemid,docname,kpdate&start=0&length=1` (`resultcount` 232,508). `kpdate` filter: Lucene syntax according to third parties, not verified. Stability of the 200: not established. To do: **re-probe from the gateway** with a declarative UA; if 200 is stable, enable as `primary/COE`; on 403, receipt `bot_challenge` then `browser` route (level 2b), never `needs_confirmation` by default. Without HUDOC, an ECHR question only receives `needs_confirmation` (measured on our benches).
   - Key: none. Rate: 3 s local (>= level-2 pacing); published limit: not established. Offline option if HUDOC stays unstable: **ECHR-OD** (`echr-opendata.eu`, 502 on 2026-10-26; repository `echr-od/ECHR-OD_process` MIT, monthly announced, freshness to check).

4. **Administrative justice, open data** (`ce_opendata`, primary, `FR-ADM`, coverage: Conseil d'Etat since 2021-09-30, CAA since 2022-03-31, TA since 2022-06-30) - `access: page` (undocumented, fragile API -> level-2 regime)
   - Endpoint: `https://opendata.justice-administrative.fr/recherche/api/Simple_Search/openData/{q}/100` (JSON back end of the public engine); at most 100 per call, total capped at 1,000, most recent first.
   - Query: several words = OR; search an **exact phrase or a number** ("473547" -> 2 results including the right order; full text does not find a 2023 order buried under recent decisions). Search by court (`model_search_juri`) announces a false total: do not use it. `Numero_ECLI` sometimes holds the literal `"undefined"`: removed.
   - Date bound: by decision date; the absence of a decision earlier than the coverage proves nothing (`coverage_from` in the receipt). Key: none. Rate: 3 s local; published limit: not established. Decisions earlier than 2021-09-30: ArianeWeb is HTML/JS without API; JADE (DILA) covers them offline.

5. **Judilibre (Cour de cassation, PISTE)** (`judilibre`, primary, `FR-JUD`, mode `gated`) - `access: api` (key required by the service, free on PISTE registration)
   - Endpoint: `https://api.piste.gouv.fr/cassation/judilibre/v1.0/search?query=&page=&page_size=50`; header `Authorization: Bearer <token>`.
   - Key: OPTIONAL, **required by the service** (PISTE token, OAuth client credentials, about 1 h validity; `PISTE_CLIENT_ID` / `PISTE_CLIENT_SECRET`). Without token: 0 request, `not_configured`. Without key the server returns 400 "Bearer... Unable to find token".
   - Response schema (`results[*]`, `decision_date`, `jurisdiction`, `chamber`, `solution`) taken from the documentation, **not verified**. Bulk export: not found (data.gouv record `api-judilibre` = OpenAPI spec only; courdecassation.fr requires JS). Key-less route: CASS/INCA/CAPP from DILA (10). Rate: 2 s local; published limit: not established.

6. **Legifrance** - two routes, two markings:
   - **PISTE API**: search and consultation in **POST** JSON, outside the declarative format; `gated` code plugin **not built**; same PISTE token; "per token" quota not quantified (piste.gouv.fr in 503 on 2026-10-26). `access: api` (key). Do not query until the plugin exists.
   - **HTML `legifrance.gouv.fr`**: **403 Cloudflare even by identifier** (robots unreadable) -> public page behind a JS challenge: `access: browser` (level 2b, ACCESS-POLICY.md), can be enabled when the browser mode is wired in the gateway; until then, no HTML reading is assumed by this plugin.

7. **HAL, law domain** (`hal_droit`, secondary) - `access: api` (robots `Disallow: /search/` on the API host has no effect, level 1)
   - Endpoint: `https://api.archives-ouvertes.fr/search/?q=&fq=level1_domain_s:shs.droit&wt=json&fl=halId_s,title_s,producedDate_s,doiId_s,uri_s,docType_s,authFullName_s&start=&rows=100`.
   - Trap: `domain_s:shs.droit` returns 0 results, `level1_domain_s` is needed. Date bound: `producedDate_s` (local re-check); server filters `producedDate_tdate`, `submittedDate_tdate`. Key: none. Rate: 1 s local; published limit: not established. Probed: 200.

8. **OpenAlex, subfield 3308 (law)** (`openalex_law`, secondary) - `access: api`
   - Endpoint: `https://api.openalex.org/works?search=&filter=primary_topic.subfield.id:3308&select=id,doi,display_name,publication_year,publication_date,primary_location,authorships,type&page=&per_page=`.
   - Key: OPTIONAL (`OPENALEX_KEY`: env or `~/.config/vp/openalex_key.key`, KEYS.md; never displayed); without key: 429 (shared budget of the IP); with key: 200 (measured on our benches: 30 of 1,019). Rate: 1 s local. Date and jurisdiction trap: a 2018 article on "KlimaSeniorinnen" deals with the Swiss procedure, earlier than the Strasbourg ruling.

9. **Conseil constitutionnel** - `access: page`: reading **decision by number** (`https://www.conseil-constitutionnel.fr/decision/<year>/<number>.htm`, HTML, 200); `/recherche/` and `/cc-webservice/` under robots.txt: opened by level 2 (ACCESS-POLICY.md names "pages of the Conseil constitutionnel"), **not probed** (not established); `/open-data` page: 404. Key: none. Established search route: **CONSTIT** on DILA (quarterly XML, updated 2026-08-20, Licence Ouverte), offline, not built.

10. **DILA open data** (`https://echanges.dila.gouv.fr/OPENDATA/`: LEGI, JORF, KALI, CASS, JADE, CONSTIT, CAPP, INCA, **CNIL** (deliberations, monthly), **BOCC** (weekly), **JORFSIMPLE**; Licence Ouverte 2.0; HTTPS and FTPS; no robots; CASS occasional, INCA/CAPP daily) - `access: api` (download): **download only**, offline plugin proposed (about 8.9 GB bootstrap, 25 to 60 GB on disk, 10 to 15 MB/day), **not built**. LEGI states to be handled as a closed mapping (`VIGUEUR`, `ABROGE`, `MODIFIE`, `VIGUEUR_DIFF`, `ABROGE_DIFF`, `MODIFIE_MORT_NE`, `TRANSFERE`), end of validity **exclusive** (`valid_until_field`), sentinels 9999-12-31 and 2999-01-01 = no end. `data.gouv.fr` (`/api/2/datasets/search/`) serves only as a catalogue; the "vectorised" versions from DINUM are not primary sources. Same offline status: **Assemblee nationale / Senat** (JSON/XML and PostgreSQL dumps, Licence Ouverte, no search API; FR preparatory works) `page`; **French Competition Authority** (data.gouv dataset JSON 221 MB + CSV, 1988 -> 2026-10-25, weekly, LOv2); **BOFiP** (data.gouv dataset, weekly, LOv2; Opendatasoft API `data.economie.gouv.fr` under robots `Disallow: /api/` -> `page`, option).

11. **European Parliament, Open Data API v2** (`europarl`, secondary `grey`, `EU`; EU preparatory works: procedures, adopted texts, questions, debates - absent from Cellar for search; teleological interpretation) - `access: api` (robots `Allow: /`); not wired
    - Endpoint: `https://data.europarl.europa.eu/api/v2` (OpenAPI, no `securitySchemes`): `/documents`, `/adopted-texts`, `/plenary-documents`, `/parliamentary-questions`, `/procedures`, `/speeches`.
    - Date bound: yes, `sitting-date-start`/`sitting-date-end`, `year`. Probe of 2026-10-26: 500 `ClassCastException` on `/adopted-texts` (reachable, parameters to adjust) -> to be typed `provider_error`.
    - Key: none. Rate: **500 req / 5 min** per endpoint. Licence: CC BY 4.0.

12. **Isidore (Huma-Num)** (`isidore`, secondary; French-speaking humanities aggregator: HAL, OpenEdition, Persee, Cairn as metadata, theses; **the only API with a date filter**) - `access: api` (robots `Allow: /api`, Crawl-delay 15); not wired
    - Endpoint: `https://api.isidore.science/resource/search?q=<q>&output=json` (probe 200); filters `date`, `discipline`, `type`, `language`.
    - Date bound: yes (`date`); local re-check. Key: none. Rate: Crawl-delay 15 s -> local interval 15 s. Terms: /about page in 403 -> not established. Replaces the OpenEdition/Persee OAI (`metadata.openedition.org/oai`, `oai.persee.fr`: robots `Disallow: /`; opened by level 2, `page`, not wired; Cairn OAI: endpoint not verified, full text paid).

13. **theses.fr API v1 (ABES)** (`theses-fr`, secondary; dated French theses) - `access: api`; not wired
    - Endpoint: `https://theses.fr/api/v1/theses/recherche/?q=<q>&nombre=<n>` (probe 200: 43,906 for "droit").
    - Date bound: yes, `dateSoutenance:([a TO b])`. Key: none. Rate: Crawl-delay 5 -> local interval 5 s. Licence Ouverte 2.0.

Identity options (never a source of claims): **API Recherche d'entreprises (DINUM)** `https://recherche-entreprises.api.gouv.fr/search?q=` (probe 200, **7 req/s per IP**, Licence Ouverte; SIREN, officers, IDCC) `api`; **BODACC / BOAMP** `https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets` (probe 200; robots: `/explore/download` forbidden, API not forbidden; rate not established) `api`; **Juricaf** (French-speaking case law, 2.03 M decisions, ODbL; no API, XML on request; robots: `/recherche/` forbidden and AI bots `Disallow: /` -> opened by level 2, named in ACCESS-POLICY.md) `page`, not wired.

Set aside: **e-Justice ECLI search** (SOAP on written request) and **N-Lex** (no API, "contains no documents"); **Conseil d'Etat ArianeWeb** (HTML/JS without API; JADE covers); **ECHR Knowledge Sharing** (non-binding guides; robots `Disallow: /search`, no API; `page`, no primary value); **Council of the EU** (403/JS pages, nothing established; `browser`, not established); **EDPB RSS** (news feed); **Doctrine.fr, Dalloz, Lexis** (no public API, paid; Lexis 403; `technical_block`: paywall); **BAILII** (terms forbid automation; `tos_forbidden`), **Caselaw Access Project** (static files), **CourtListener v4** (anonymous or free token, 5 req/min, probe 200; `api`): outside the FR/EU scope, the only machine route if a US plugin is born.

## Discipline biases

Shared catalogue: `vp-bias-catalogue/1`, discipline file `law` (`usage = "signal"`, 7 defects, 12 verified references). Law **is not measured** against the catalogue set; its central biases belong to the **mechanical verifier** on a primary base, not to the LLM judge. The four rules below are coded as verifications and taken over here as is with their catalogue name; they can only harden a verdict, never raise it; missing data gives `needs_confirmation`, never a pass.
- **`law.not_in_force`** - rule `in_force_at_date`: text in force **and applicable** at the date of the question. Start <= date; end of validity inclusive in Cellar, exclusive in LEGI; 9999-12-31 and 2999-01-01 = no end; application date later -> `needs_confirmation`; "in force" flag contradicting the dates -> unreliable record (`needs_confirmation`). Real examples: directive 95/46 in force until 2018-05-24 inclusive; GDPR entered into force on 2016-05-24, applicable on 2018-05-25; directive 2006/24 void from the outset (end = entry into force). Also applies to the version of the text (`version_pinned` on the CELEX).
- **`law.wrong_jurisdiction`** - rule `jurisdiction_match`: same order, or order contained in that of the question (`FR` contains `FR-ADM`); EU or ECHR source for a French question -> `needs_confirmation` (direct effect, transposition); other French order (judicial for an administrative question) -> `needs_confirmation`; foreign order -> `unsupported`. Doctrine is exempt, a primary source never, even coming from another plugin. Example: CE 473547 for an EU-law question -> `unsupported`.
- **`law.overruled`** - rule `not_overturned`: a court of last resort (`CJ`, `CO`, `CE`, Cour de cassation) passes; otherwise an explicit history is required (`set_aside_by`, `none` = checked, nothing found); without history (administrative tribunal, HUDOC) -> `needs_confirmation`. Example: T-286/09 (Intel) set aside by C-413/14 P -> `unsupported`.
- **`law.doctrine_for_primary`** - rule `source_tier`: a decisive claim has at least one primary source; doctrine alone -> `needs_confirmation` ("find the primary text"); doctrine next to a primary source is not penalised. Example: KlimaSeniorinnen with HAL and OpenAlex only, HUDOC unavailable -> `needs_confirmation`.
- **`law.non_binding`**: non-binding authority presented as binding; obiter dictum taken for the operative part. The opinions of the Advocates General (CELEX `CC`) are excluded from `eurlex_caselaw` for this reason; they are also a leakage risk in evaluation (they contain almost the whole answer before the ruling).
- **`law.fabricated_citation`**: invented or unverifiable citation (catalogue reference: Mata v. Avianca); every reference must resolve (CELEX, ECLI, decision number) in its primary source.
- **`law.misgrounded`**: real source that does not support the proposition; this is the general case of level 1 (`DISTORTED` / `ABSENT`).
- Data traps observed: dates attributed to the wrong act by Cellar (HTTP 200); Cellar twins; invalidation by preliminary ruling under another predicate; false total of the administrative justice; LEGI states `MODIFIE_MORT_NE` / `VIGUEUR_DIFF` (versions never or not yet in force); date and jurisdiction trap in doctrine (Swiss procedure earlier than the ECHR ruling).
- To be completed by the owner.

## Output format

One **card per legal source** cited (text, decision, doctrine), fields in order (common format: the `card.json` schema checked by `tools/validate_card.py`):
1. **Identification**: type (`text` / `decision` / `doctrine`), official title, **CELEX** or **ECLI** or decision number (and application number for the ECHR), court or author of the act, date of the act or decision, **tier** (`primary` / `secondary` / `grey`), **legal order** (`EU`, `COE`, `FR-ADM`, `FR-JUD`), source consulted and its coverage (`coverage_from`).
2. **Validity** (texts): `in_force_from`, `applies_from`, `in_force_to` (inclusive or exclusive depending on the source), "in force" flag, LEGI state if any, version (consolidated CELEX); **date of the question** and result of `in_force_at_date` (`supported` / `needs_confirmation` / `unsupported`).
3. **History** (decisions): court of last resort or not; `set_aside_by` (identifier) or `none` (checked) or `unknown`; result of `not_overturned`.
4. **Claim** (A1, A2...) decomposed: proposition of law, text or decision that grounds it, legal order targeted by the question, date of the question; result of `jurisdiction_match` and `source_tier`.
5. **Citation**: excerpt from the **official text** (never from a `_RES` summary, a press release or the Advocate General's opinion), checked fragments.
6. **Signals**: `law.*` catalogue ids triggered, with the observable trigger (never a verdict).
7. **Verified status**: level-1 verdict per claim; host verdict = the strictest between the judge and the four rules.

At the end of the report: receipt of the sources (key sources `not_configured`, HUDOC `bot_challenge`, OpenAlex quotas), announced coverage (what the system cannot see: Legifrance, Judilibre without token, Conseil constitutionnel for search, ECHR), exclusions.

## Verification rules

Level 1 (`tools/verifier/ROLE.md`, the level-1 verifier role; fragments checked by `tools/verifier/citation_check.py`), plus the host's mechanical checks (measured on our benches: 20 of 20 mutants killed, control survived; 12 real verifications matched the expected answers on 2026-10-22). They take the strictest between the judge's verdict and their own result; missing data gives `needs_confirmation`. Audit mode (SKILL.md, section "Audit mode") is recommended for this plugin: exhaustive verification of every atomic claim; set VP_MODE=audit or ~/.config/vp/mode.
1. **`in_force_at_date`** (`law.not_in_force`) on `eurlex_legislation`: `valid_from_field = in_force_from`, `applies_from_field = applies_from`, `valid_to_field = in_force_to`, `in_force_flag_field = in_force`; mandatory cross-check of the flag and the dates (Cellar was wrong once in HTTP 200).
2. **`version_pinned`** (`law.not_in_force`): the card cites the CELEX of the version; without version, `needs_confirmation`.
3. **`jurisdiction_match`** (`law.wrong_jurisdiction`): `jurisdiction` field of the record against that of the question; `also_binding = { FR = [EU, COE], EU = [COE] }`; `skip_tiers = [secondary, grey]`.
4. **`not_overturned`** (`law.overruled`): `history_fields = [set_aside_by]`, `clear_value = none`, `final_courts = [CJ, CO, CE, cc]`; both Cellar annulment predicates are read; records grouped by CELEX before the rule.
5. **`source_tier`** (`law.doctrine_for_primary`): `min_tier = primary`; below or unknown -> `needs_confirmation`.
6. **Citation**: the source of a fragment is the official text; a fragment taken from a `_RES`, a press release or an Advocate General's opinion makes the claim `SOURCE-UNAVAILABLE` for the proof.
7. **Reference that does not resolve** (CELEX, ECLI, number, application) -> `law.fabricated_citation` flagged and claim `ABSENT`.
8. **Coverage**: a negative claim ("no decision") is admissible only within the coverage window of the source (`coverage_from`) and with the receipt of the query by number or exact phrase; outside the window or with HUDOC blocked -> `needs_confirmation`.
9. **False total, null literals**: capped total (1,000) or partial page = `bounded`, never `complete`; `"undefined"` removed (`null_literals`).
10. **Keys**: no PISTE token nor OpenAlex key appears in a card, a receipt or a URL.
11. **Mechanical retraction check (rule shared by all plugins)**: for every retained DOI (doctrine: HAL, Isidore, theses.fr, OpenAlex), the verifier reads Crossref `/works/<DOI>`: `has-update` then `update-to` (`update-type`: `retraction`, `erratum`, `expression_of_concern`), and cross-checks with Retraction Watch (CSV `crossref/retraction-watch-data`); **no model call** (measured on our benches: 30/30 detected). `unknown` stays `unknown`. For primary sources, the counterpart remains `not_overturned` (rule 4). To be wired into `tools/verifier.py`.
