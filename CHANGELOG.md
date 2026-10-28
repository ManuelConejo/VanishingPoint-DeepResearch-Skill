# Changelog

## v0.1 - 2026-10-27 - first packaged release

Everything in this release was either measured on our benches before being adopted, or is a packaging change with its own test.

### Measured and adopted
- Engine: the rewritten deep-research method (frame, 5-10 angles, 3-5 parallel searches, triangulation, stop on saturation):
  recall 48.9 %, +43.9 points over memory alone (11/11 cases). Snowballing as the main method (+1 point recall, -9 points
  precision) and verification as a collection filter (recall 48.5 -> 29.8 %) are forbidden by SKILL.md.
- Downstream verification in a separate fresh-context call (`tools/verifier.py`, role file `tools/verifier/ROLE.md`,
  machine-checked fragments): -4.2 points of false claims at equal recall (50 questions); hardened run 81/81.
- Report form: eight fixed sections in argued prose, numbered bibliography, machine annex derived by a last short call
  and checked by `tools/validate_card.py` (12 checks) and `tools/validate_result.py`.
- v3 cost levers (one verifier, one pass; verify what carries a decision; short briefs by reference; cheaper search model;
  output-token ceilings): halves the cost of the exhaustive variant; the standard mode stays about 2x the reference method.
- Whole reading before verdicts (code plugin, `tools/whole_reading.py`, `tools/condense_repo.py`): 6 code cases, exclusive
  verified findings in 5 of 6 (17 against 14), three LLM judges 16/18, owner 5/5 blind; +0.9 to 2.6 USD per case.
- Date-bounded gateway (`tools/gateway.py`): 19/19 forbidden reviews stay unfindable offline and online; arXiv engine added.
- Optional keys announced once (`tools/check_keys.py --announce`), free-key suggestions (`--suggest`), three-level
  access policy (ACCESS-POLICY.md), context capsule for code (`tools/code_capsule.py`, nothing of X executed).
- Audit mode (optional, never default): the exhaustive verification variant, -6.7 points of false claims
  [-12.2; -1.1] at 6 to 7x the standard cost; switched on by `VP_MODE=audit`, `~/.config/vp/mode` or an explicit request.

### Packaging changes in this release (tested, not re-measured)
- Everything is in English: file names, tool names, options, JSON keys, statuses (FOUND, DISTORTED, ABSENT,
  SOURCE-UNAVAILABLE, INVALID, UNVERIFIED), working files (`searches/`, `REPORT.md`, `card.json`, `result.json`,
  `mechanisms.json`, `state/`). The verifier role file and the whole-reading prompt are English translations of the
  measured French texts (same rules, same output format); they were not re-measured after translation.
- Host profiles: every tool that calls a model reads `tools/config.json` `model_command` (profiles `claude` = `claude -p`,
  `openai` = `codex exec`), selected by `VP_HOST` or the config; SKILL.md gives the Claude Code / Codex CLI equivalence
  for sub-agents. Unit tests cover both profiles with a fake executable.
- `tools/whole_reading.py` generalised from the internal tool: no case table, no bench wrapper; input = the run directory
  (scope.md, searches/*.md, capsule.md, state/calls.jsonl), repositories and SHAs from scope.md or arguments; caps 400 k / 200 k
  characters; same material rules; output `searches/whole-reading.md` + `state/whole-reading/receipt.json`. Its tests
  rebuild the X material of two reference cases identically.
- The verifier's dependencies (role file, citation check, full-text fetch) ship inside `tools/verifier/`; the bench grader
  is not shipped. Historical key fallback directories are removed (keys: environment, then `~/.config/vp/`).
- All paths are relative to the skill directory; no absolute path, no e-mail, no key value in the product.
- Acceptance runs of this release: one real Claude Code run (claude-opus-5-5 orchestrator, sonnet sub-agents) on an academic
  question, report validated by `validate_card.py`; the Codex CLI run of the same question failed before any tool call because
  the host container forbids the user namespaces that Codex's sandbox needs (error recorded; sandbox not bypassed): Codex
  discovery and reading of the skill are established, a full Codex run is not.

### Measured and NOT adopted (not shipped)
- The earlier VanishingPoint algorithm (recursive hunt, mirror effects): abandoned, beaten by the rewritten reference method.
- The exhaustive v2 as default (6.8x cost) and the v3 at 3.5x: v3 is shipped as the standard mode without the cost target
  being met; v2 survives only as the optional audit mode.
- The code plugin as a competing finder: no variant beat the plain model on "what would Y bring to X" (recall 0.50 vs 0.45);
  kept only for its capsule, seams and whole reading.
- GitHub evidence dossier (adoptions, reverts): rejected in cross-family review (adopted != useful, temporal leak, n too small).
- Contradictor mode (second model family), evidence index across reports, repository-map selection of the read block,
  wiring of the non-API sources: on the waiting list, not measured, not shipped.

## v0.1.1, 2026-10-27 (after the Codex CLI acceptance run)
- Codex CLI run passed end to end (report validated, 5 gateway searches, 0 USD) in a throwaway container with Codex's own sandbox
  disabled; the container is the isolation boundary there (README, "Codex CLI").
- Fixed: the model sub-command (`codex`) was not found from Codex's login shell, so the verifier returned every claim as
  UNVERIFIED (correctly flagged in the report, but nothing verified). `tools/verifier.py` and `tools/whole_reading.py` now
  resolve the executable (`~/.npm-global/bin`, `~/.local/bin`, `/usr/local/bin`) when it is not on PATH.
- Added: an exact inventory of plugins and tools at the top of SKILL.md section 1 (the Codex agent guessed 11 non-existent
  file names before listing the directory).
- Still unmeasured: the quality of the verification step under OpenAI (first run had none).

## v0.2.0, 2026-10-28 - contradictor option (measured, adopted)

### Measured and adopted
- Contradictor after the report (`tools/contradictor.py`, prompts `tools/prompts/CONTRADICTOR*.md`, SKILL.md "Contradictor",
  plugins/code.md "Contradictor after the report"): optional, absent by default. A model of another family than the author (`openai[:<model>]` = the
  Codex CLI, `claude[:<model>]` = `claude -p`, `<provider>:<model>` = any OpenAI-compatible API named in `tools/config.json`:
  openrouter, gemini, openai-api, mistral, ollama or one the user adds; no model name is fixed in the skill) reads the report, Y and X without tools and claims at most 3 false statements
  and 3 misses with references; mechanical check, exclusivity call, fresh-context rereads with the cited extracts only;
  `contradictor.json` is applied by the orchestrator (annotation "contradicted by <family>", added findings verified like any other).
  Measured on our benches on the 6 code reports of the whole-reading duel, frozen protocol and criterion: every family adoptable
  (cases with a true detection 6/6 each; true detections against added errors: Gemini 14/11, Kimi 20/6, Codex 20/8; models of that day:
  `google/gemini-4-argon` and `moonshotai/kimi-k3.1-pro` through OpenRouter, `gpt-5.6-sol` through the Codex CLI); the measure
  cost 6.95 USD; in use about 0.26 USD per contradictor call and 0.6 USD of rereads per report.
- Known limits, stated in the plugin: n = 1 per cell; one reread model for every family; 36 of 37 misses confirmed by that reread;
  exclusivity judged by two other families on our benches and by the host model in the product; the contradictor prompt is the
  measured text with English JSON keys, the reread and match prompts are English translations of the measured French texts
  (same rules, same answers), not re-measured after translation; `claude` as contradictor, other models or providers, and anything outside the code plugin not measured.

### Packaging
- `check_keys.py` prints the configured contradictor families (names only, and whether each provider's key variable is present)
  before the mode line; `KEYS.md` documents the provider keys; `tools/config.json` gains a `contradictor` block (families,
  providers = url + key variable name, request fields, caps, reread model per host profile, empty = the host CLI's default).
- Tests: `tests/test_contradictor.py` (fake OpenRouter endpoint, fake Codex and claude executables: no network, no cost),
  `tests/test_check_keys.py` extended.

## v0.2.1, 2026-10-28 - free models, generic providers, review fixes, test campaign

### Models and providers left free
- No model name is fixed in the code: a contradictor family is `openai[:<model>]` (Codex CLI), `claude[:<model>]` (`claude -p`) or
  `<provider>:<model>` for any OpenAI-compatible chat-completions API listed in `tools/config.json` `contradictor.providers`
  (openrouter, gemini, openai-api, mistral, ollama, or one the user adds there or in `VP_CONTRADICTOR_PROVIDERS`), each with its
  own key variable. Without a model, a CLI uses its own default.
- The verifier and the whole reading take their model per host profile (`verifier.model` = `{"claude": "opus", "openai": ""}`:
  an alias that follows the vendor, or the CLI default); `VP_MODEL` / `--model` override it.

### Fixed (fresh-eye code review, then tests)
- `verifier.py`: a card id or a source key could escape the work directory (`rmtree` of a model-written path): file-system-safe
  names; DOI keys no longer crash; `sources/<key>.txt` and `sources/<key>/source.txt` both read; a leftover account-name guard removed.
- `contradictor.py`: the key is never sent on a redirect nor over plain http (localhost excepted); one-pass prompt filling (a literal
  `{X}` in a report is no longer substituted); malformed JSON lists no longer crash a run; verdicts parsed as whole words; a blank
  `~/.config/vp/contradictors` counts as absent; the match call counts against the ceiling.
- `whole_reading.py`: one-pass prompt filling; no unconditional `chown` of the user's files (optional `chown` in config);
  references without a file extension (`Makefile:12@sha`) are recognised.
- `condense_repo.py` accepts a working copy as well as a bare repository; `code_capsule.py` sees single-quoted `__main__` guards;
  `gateway.py`: an invalid GitHub token no longer crashes `sources`, a non-numeric reference year no longer fails `references`;
  `paper-code` accepts `arxiv:<id>`; `check_keys.py` says when an API family lacks its model id.

### Test campaign (2026-10-28)
- 73 offline unit tests green; blank install; every wired source of every plugin on the live network (no year after T); temporal
  barrier online: 20/20 forbidden reviews unfindable; capsule, condensation, whole reading (real, Codex CLI) and contradictor (real,
  Codex contradictor + Claude rereads) on real repositories; one end-to-end Claude Code run (biology, validated, 32 FOUND / 3
  DISTORTED, plugin biases named in the appendix).
- Known limits found: OpenAlex may return fewer than `--n` under the strict date barrier; `provenance` reads only the latest
  Software Heritage visit; the verifier under Codex needs Codex's sandbox (user namespaces) to read its files, otherwise every claim
  stays UNVERIFIED (safe, flagged). Not changed: they touch measured components.

## v0.2.2, 2026-10-28 - NCBI key wired, suggestions limited to keys that act

- `NCBI_API_KEY` is now sent as `api_key=` on every PubMed E-utilities call (esearch, esummary, efetch), with the 10 req/s
  interval (0.11 s) instead of 3 req/s (0.45 s); without the key nothing changes. Offline test added; PubMed checked online
  without a key. Not checked with a real NCBI key.
- `check_keys.py --suggest` proposes only keys the gateway really sends today (`OPENALEX_KEY`, `NCBI_API_KEY`,
  `VP_GITHUB_TOKEN`): a key declared with no effect (engine not wired, or key not passed, such as `SWH_TOKEN`, `S2_API_KEY`,
  `PISTE_*`) is never suggested. Found in the 2026-10-28 end-to-end run, which suggested the NCBI key while it had no effect.

## v0.3.0, 2026-10-28 - law engines wired

- `gateway.py` wires four keyless law engines declared in `plugins/law.md`: `eurlex` (Cellar SPARQL, legislation and CJEU case
  law: grouped by CELEX, `_RES`/`_INF`, Advocate General opinions `CC` and OJ judgment notices `CA`/`TA`/`FA` set aside, both
  "declares void" predicates read, no `OPTIONAL` join; HTTP 5xx or timeout = `provider_error`), `justice-administrative`
  (open data back end, level 2 `page`, 3 s, stop on 403/429, decision-date range on the server, `bounded` totals with
  `coverage_from`, `"undefined"` ECLI removed), `hal` (`level1_domain_s:shs.droit`, production and deposit dates filtered on the
  server), `theses-fr` (`dateSoutenance` range, 5 s). Each filters on the provider side to the eve of T and rechecks every record
  locally (act, decision + upload, defence, production + deposit dates < T; forbidden DOI, CELEX, ECLI, NNT, HAL id, titles; no
  date = refused). Cellar validity fields are post-T knowledge when the notice changed on or after T: then only dates before T are
  served, the current "in force" flag is masked, voiding rulings dated on or after T are never served.
- `read` serves `celex:` / `ecli:` (EU and FR administrative) / `ja:` / `hal:` / `thesesfr:` under the same barrier: official text
  start through Cellar content negotiation, administrative decision full text, HAL and theses.fr abstracts; `citing` and
  `references` refuse law ids cleanly. `verifier.py` passes these ids to `read`. `fetch` takes optional headers (in the cache key),
  per-host timeouts and immediate stops (`STOP`).
- Tests: 6 offline tests added to `test_gateway.py` (per engine: before T visible; after T, day T, partial date at the year of T,
  forbidden id or title, no date refused; provider-side filter on the eve of T in the URL; no key nor e-mail in any URL; read under
  the barrier; Cellar 500 typed). Full offline suite green as uid 1000 on a copy (8 files).
- Live probes (T 2026-10-26 and early T 2019-06-01 / 2023-01-01, plus reads): every engine answered; 0 record dated on or after
  T. Known limit: a first Cellar free-text query on a common single word can take 60-90 s (`provider_error` past 90 s).
- Not wired: HUDOC (re-probe planned), Judilibre and Legifrance (PISTE token / POST API, HTML behind a bot challenge), Isidore and
  European Parliament (planned). EUR-Lex HTML answers 202 empty to robots: not used. The legal verification rules
  (`in_force_at_date`...) stay documented, not automated.

## v0.3.1, 2026-10-28 - more keyless engines, key fixes

- Four keyless engines wired, each behind the same date barrier (provider filter at the eve of T where the API allows it,
  then every known date < T, forbidden identifiers and titles):
  - `clinicaltrials` (biology): ClinicalTrials.gov API v2, `search-clinicaltrials`, `read nct:<id>`; registered trials,
    published or not (publication-bias check). First submitted AND first posted < T (provider: `AREA[StudyFirstPostDate]
    RANGE[MIN,<eve>]`); results only when posted < T; a record updated on/after T keeps id, title, conditions, first dates and
    masks status, phase, enrollment, start date, texts.
  - `dblp` (cs-ai): through the SPARQL endpoint `sparql.dblp.org` (title word index, year < year of T on the provider side).
    The search API `dblp.org/search/publ/api` answers an Anubis anti-robot page (HTTP 202): not used, never worked around.
    Every year (publication AND event) < year of T; CoRR dated by its arXiv id (month of v1 < T); other DOIs rechecked on
    Crossref. 429 -> `rate_limited` with Retry-After, server timeout -> `provider_error`, non-JSON -> `bot_challenge`.
    `read dblp:<key>` (metadata only).
  - `econbiz` (finance): ZBW EconBiz API, `search-econbiz`, `read econbiz:<id>`; indexing date `econbiz_created` and year
    bounded on the provider side; free-text dates parsed (EN/DE months, quarters, intervals), year alone -> `year_before_T`;
    DOI rechecked on Crossref. Terms read: free, polite use, no AI clause.
  - `osv` (code engine): `vulns <ecosystem>:<package>@<version>` (POST `api.osv.dev/v1/query` through `CodeClient`) and
    `read osv:<id>`, only when a plugin declares `osv`. `published` absent or >= T -> refused; modified on/after T ->
    summary, details, ranges, severity masked; no count of today's advisories.
- `SWH_TOKEN` is now sent (`Authorization: Bearer`, `archive.softwareheritage.org` only, never on a redirect; interval 3 s
  instead of 6 s, both in `config.json` `code_intervals`); `check_keys.py` marks it `passed`, so `--suggest` may propose it.
  Checked live with a fake token: 403 `AuthenticationFailed`, then the anonymous retry answered 200.
- A key the provider rejects no longer breaks its source: NCBI 400 "API key invalid", OpenAlex 401/403, Software Heritage
  401/403 -> one retry without the key, key dropped for the rest of the run (`<state>/keys-invalid.json`, names only), flag
  `key_invalid: [NAME]` on every answer, in `sources` and in the journal. Checked live with `NCBI_API_KEY=invalid-test-key-000`
  (search and read return results) and a fake `OPENALEX_KEY`. The NCBI 400 body echoes the key: it is read, never kept.
- Tests: `tests/test_engines_extra.py` (18, offline); `test_code_sources.py` (host list + `api.osv.dev`) and
  `test_check_keys.py` (SWH now suggested) adjusted. Live probes at T 2026-10-26 and 2019-06-01: 0 date on/after T.

## v0.3.2, 2026-10-28 - AI and code engines

- cs-ai: `openreview` wired on `/notes/search` (API v1 and v2; `/notes?id=`, `?forum=`, `/notes/edits` answer 403 ChallengeRequiredError: not used). No provider date filter: forum visible only when cdate, tcdate, odate, pdate, mdate < T; tmdate on/after T masks abstract, venue, decision; replies (reviews, decision) served only when cdate, tcdate, mdate, tmdate < T; a decision on/after T is never served. `read openreview:<id>` after a search (abstract, reviews, decision; decision notes often missed by the reply search). Terms: no anti-automation clause, comments CC BY 4.0.
- cs-ai: `zenodo` wired (keyless; created and publication_date bounded on the provider side and rechecked; DataCite DOIs: no Crossref recheck; related identifiers checked against the forbidden list; description masked when updated on/after T); `read zenodo:<id>`.
- cs-ai: `hal-info` (HAL `level0_domain_s:(info OR stat)`); the law `hal` engine keeps `shs.droit`. `paper-code` (HF Papers) declared by cs-ai, same barrier as code.
- code: `usage <registry>:<package>` (engine `ecosyste.ms`): release before T required, latest release before T (`published_before`), counts, maintainers, licences marked `as_of: "now"`.
- code: Stack Exchange left `tos_forbidden` (Acceptable Use Policy forbids automated collection for building, testing or benchmarking generative AI tools; the official MCP forbids caching).
- check_keys: names served by a declared wired code engine (github, sourcegraph -> code; deps.dev, pypi, npm, crates -> versions; hf-papers -> paper-code; software-heritage -> provenance) shown "served by", no longer "not wired".
- Tests: `tests/test_engines_b3.py` (11, offline). Live probes 2026-10-28 at T 2026-10-26 and 2021-01-01: 0 post-T leak.

## v0.3.1, 2026-10-28 - legal rules automated, display fix

- `tools/law_checks.py` (new, stdlib, offline by default): the legal verification rules of `plugins/law.md` (1 to 9) run mechanically on a run directory after `verifier.py`: `resolves` (`law.fabricated_citation`), `official_text` (`_RES`/`_INF`, press release, Advocate General opinion; `law.non_binding`), `in_force_at_date` and `version_pinned` (`law.not_in_force`; inclusive Cellar end, exclusive LEGI end, 9999-12-31/2999-01-01 = no end, application date, in-force flag cross-checked with the dates, validity masked by the gateway under T), `jurisdiction_match` (`law.wrong_jurisdiction`), `not_overturned` (`law.overruled`; set-aside dated after the question date ignored), `source_tier` (`law.doctrine_for_primary`), `coverage` of negative claims and `bounded_total` (`law.misgrounded`). Each rule gives `supported` / `needs_confirmation` / `unsupported` with its observable trigger; missing data never passes. Writes `law_checks.json` (final status = strictest of the verifier's and the mapped rule: foreign order and unresolved reference -> ABSENT, not the official text -> SOURCE-UNAVAILABLE, the others -> DISTORTED with the trigger as discrepancy; `needs_confirmation` keeps the status and lists the claim in `to_flag`). Never edits the report; the orchestrator applies it (plugins/law.md, "Applying it"). `--fetch` re-reads missing records through the gateway under the date barrier.
- `tools/verifier.py`: law identifiers in `card.sources` (`celex`, `ecli`, `ja`, `hal`, `thesesfr`) are read through the gateway, and the record read is saved as `sources/<key>/record.json` for `law_checks.py`.
- `plugins/law.md`: verification rules now "automated by tools/law_checks.py", inputs, mapping and how to apply `law_checks.json`; `SKILL.md`: inventory and one pointer in section 7.
- Tests: `tests/test_law_checks.py` (22 tests: the real examples of the plugin, run-directory mapping, command line, verifier record; 44 of 44 mutants caught, control passing). Live check without a model on 2026-10-28: 13 of 13 claims as expected on real Cellar and administrative-court records at two question dates.
- Fix: `gateway.py sources` lists names served by a declared code engine under `served_by`, not `not_wired`.
- Fix: `validate_card.py` and `verifier.py` accept every id an engine returns without DOI (`celex`, `ecli`, `ja`, `hal`, `thesesfr`, `nct`, `dblp`, `econbiz`, `osv`, `openreview`, `zenodo`) as a source identifier; before, a card citing only such ids failed check 2. Test added.

## v0.3.3, 2026-10-28 - HTML and PDF export

- New `tools/export_report.py <dir> [--pdf] [--out DIR]` (standard library, offline, installs nothing): `REPORT.md` ->
  `REPORT.html`, one self-contained page (inline CSS, no script, no external resource, CSP `default-src 'none'`): header
  from `card.json` / `run.json` / `verdicts.json` / `scope.md` (question, T, plugins, mode, verification counts, calls),
  contents, each `[n]` linked to its bibliography entry with back-links, `doi:` / `pmid:` / `arxiv:` and URLs clickable,
  print CSS (A4, page numbers, new page before Bibliography and Methodology Appendix, no break inside table rows).
  All report text is HTML-escaped; links kept only for http(s), mailto and in-page anchors; images become their alt text.
- `--pdf`: first converter found among WeasyPrint (module, then command; every URL fetch refused), Chromium/Chrome headless
  (DNS blocked; `--no-sandbox` only on a retry inside a container, as root or when the sandbox cannot start), wkhtmltopdf,
  pandoc with a local PDF engine. None: HTML kept, one line, exit 0.
- SKILL.md section 8: run the export after validation and list the files in the final message; inventory updated. README: one line.
- Tests: `tests/test_export_report.py` (escaping of `<script>`, `"><img onerror>`, `javascript:` links; header with and
  without JSON; `--pdf` with no converter; real `%PDF` when a converter exists). Checked on two real reports with
  WeasyPrint 68.1 and Chromium 150 (7 and 11 A4 pages).

## v0.3.4, 2026-10-28 - open the report

- `export_report.py --open` shows the PDF (else the HTML) with the desktop viewer (`open` on macOS, `xdg-open` with a display on
  Linux, `start` on Windows) and does nothing, silently, on a server or in a container. SKILL.md runs export with
  `--pdf --open`. Test added.

## v0.4.0, 2026-10-28 - study table and bibliography exports

- `tools/export_data.py <run dir> [--out DIR]` (stdlib, offline), run after `export_report.py` in section 8:
  - `studies.csv`: one row per study of `result.json` (id, title, year, every criteria key met, confidence, basis,
    claims citing it counted per `verdicts.json` status, its `[n]`); RFC 4180, UTF-8 without BOM, formula injection
    neutralised (a cell starting with = + - @ gets a leading apostrophe).
  - `references.bib`, `references.ris`, `references.json` (CSL-JSON): one record per bibliography entry, completed by
    `card.json` and `result.json`; type guessed from the identifier (article, preprint, software, dataset, legislation,
    case, trial, thesis); a field the run does not give stays empty; VP id in note / AN; stable unique BibTeX keys,
    special characters escaped.
- `tests/test_export_data.py` (offline, 7 tests). SKILL.md (inventory, section 8) and README (export step): one line each.

## v0.4.1, 2026-10-28 - living review (update of a previous run)

Packaging feature, tested offline, not measured.
- `tools/living_diff.py OLD_DIR NEW_DIR [--out FILE]` (offline, stdlib, no model): compares two runs of the same question at T1 < T2 and writes
  `UPDATE.md` + `update.json`; never edits either run. Sources matched by normalised identifier (DOI case and resolver prefix, arXiv
  version, pmid, PMC/NCT/CELEX, code `file@SHA7`; fallback title + year); added sources split into new evidence (dated on or after T1)
  and older ones (seen at T1 but not kept / not found at T1 / undetermined); dropped sources (seen at T2 or not retrieved); finding verdicts
  matched by title similarity, verdict words compared; first sentences and one-line summaries side by side; verification counts;
  newly DISTORTED sources and retraction/erratum/concern mentions. Exit 2 when a dir lacks card.json or REPORT.md.
- SKILL.md section 8, "Updating a previous run": normal run at today's T in a new directory, then the tool; its paragraph goes under
  `### What changed since <T1>` in the Methodology Appendix (no ninth section, `validate_card.py` unchanged). Inventory and README updated.
- `tests/test_living_diff.py`: fixture runs and a smoke test on a real run whose updated report still passes `validate_card.py`.

## v0.4.2, 2026-10-28 - bioRxiv and medRxiv preprints

- New keyless engines `biorxiv` and `medrxiv` (plugins/biology.md, section 10; `access: api`). api.biorxiv.org has no keyword search: the words go to Europe PMC (`SRC:PPR AND PUBLISHER:"bioRxiv"|"medRxiv"`, provider bound `FIRST_PDATE` and `FIRST_IDATE` <= eve of T), each hit is dated on `api.biorxiv.org/details/<server>/<DOI>` (one row per version). Preprint DOIs `10.1101/...` and `10.64898/...` (openRxiv).
- Barrier: version 1 posted < T (and Europe PMC first publication and indexing < T); served metadata and abstract = latest version posted < T, later versions never read (`later_versions_masked`); preprint DOI, published-article DOI (any date) and every version title checked against the forbidden lists; no date -> refused. `published_doi` (journal, year) shown only when Crossref attests deposit AND publication < T. Items `doi:<preprint DOI>`, `type: preprint`, `peer_review: not peer reviewed (preprint)`.
- `read biorxiv:<DOI>` / `read medrxiv:<DOI>`; `read doi:<preprint DOI>` now routed there (the Europe PMC core record carried the latest version, possibly after T); `citing` / `references` of a preprint gated on v1 < T. `validate_card.py` and `verifier.py` accept `biorxiv` / `medrxiv` keys.
- Rate 1 req/s on api.biorxiv.org, stop on 403/429; a failing host stops the call (typed `provider_error`, never an empty result).
- Tests: `tests/test_engines_rxiv.py` (6, offline). Live "SARS-CoV-2 spike antibody": bioRxiv 20/20 at T 2026-10-26 (4,027 announced), 20/20 at T 2020-06-01 (296), medRxiv 20/20 at T 2020-06-01 (148); 0 date on/after T; reads at T 2020-03-25 (v2 of 3 served, Nature link hidden) and T 2020-03-20 (refused, v1 on 2020-03-22).

## v0.4.3, 2026-10-28 - fixes from the end-to-end runs

Code only (no change to SKILL.md nor to the role and prompt files); found by the two end-to-end runs of 2026-10-28 (law, cs-ai).

- `tools/verifier.py check` no longer crashes (`KeyError: 'verdicts'`): it reads the `claims` written by `verify` (status, card key) and the
  older `verdicts` files; `tools/verifier/citation_check.py` reads both too. Unreadable file: message, exit 2.
- `tools/verifier.py verify --T`: every gateway reading is saved under `sources/<key>/` (`record.json` + `source.txt`, the text the verifier
  received), for every id kind, not only law ids; default folder `--sources`, else `--work/sources`, else `sources/` next to `--out`.
  A saved reading is read back as "record + abstract", never as a full text. The fragment check of section 7 is possible again.
- `tools/validate_result.py`: accepts every id kind the gateway serves (celex, ecli, ja, hal, thesesfr, nct, dblp, econbiz, osv, openreview,
  zenodo, biorxiv, medrxiv, pmcid) and code ids `<path>@<SHA>`; the law run had dropped its CELEX, ECLI and thesis sources.
- `tools/law_checks.py`:
  - `in_force_at_date` no longer holds a repealed text against a claim about its end (repeal, expiry, "ceased", "replaced by", end of
    validity) or a claim dated within its validity; a claim relying on the text as current law stays DISTORTED (run case "validity ending
    on 2018-05-24" + controls, 6 new mutants).
  - Missing records are read through the gateway automatically when T is known (`--T` or `state/journal.jsonl`), under the date barrier;
    `--fetch` forces, `--no-fetch` stays offline; the output reports `fetch` (mode, missing, fetched, refused) and `summary.fetched`.
  - A `sources/<key>/source.txt` that is not a gateway record (invalid JSON, plain text) is skipped with its reason (`note`), never a crash.
  - `scope.md` labels (`Question date:`, `Legal order:`) are also read after a sentence on the same line.
  - Real law run, offline as delivered: 12/12 needs_confirmation, 0 checked; now: 9 records fetched, 12 checked, 0 changed (the false
    DISTORTED of the 95/46 claim gone), 1 flagged (doctrine only).
- `tools/gateway.py`:
  - `read celex:` of a judgment longer than 20,000 characters: start + marked elision + operative part ("On those grounds, the Court ...
    hereby rules" / "Par ces motifs"); `text_source` says `start + operative part`; a long act is cut with a mark. Live: C-131/12, C-136/17.
  - `search-justice-administrative`: no relevance order exists (probe: no score); the receipt says "sorted by date, most recent first" and
    to search a decision by number or exact phrase; new `--court <CE|TA75|CAA69>` and `--from/--to YYYY-MM-DD` (window kept before T),
    journaled as `filters` (live: "déréférencement" 492 decisions, 21 with `--court CE`). `plugins/law.md`: factual lines for both.
- Tests: test_verifier, test_validate_result, test_law_checks, test_gateway extended; 15 offline files green.

## v0.4.4, 2026-10-28 - full text pinned before T

Fix of a temporal leak: `tools/verifier/fetch_fulltext.py` (`verifier.py --fulltext`) read the latest arXiv / bioRxiv / medRxiv version.
- Date rule of the gateway applied to full texts: nothing dated on or after T is read. `verifier.py` passes `--T`; no T -> no full text
  (`REFUSED`, abstract only through the gateway), no request sent.
- arXiv: version dates from OAI-PMH arXivRaw (`oaipmh.arxiv.org`, level 1); the last version submitted before T (a version on day T is
  excluded, an explicit `vN` is a ceiling); LaTeX -> HTML -> PDF of that version only (`arxiv.org/{e-print,html,pdf}/<id>vN`).
  `meta.json`: `version`, `version_date`, `versions_total`, `later_versions_masked`.
- bioRxiv / medRxiv: the last version posted before T is named from `api.biorxiv.org`; its full text exists only on `www.biorxiv.org` /
  `www.medrxiv.org` (robots.txt disallows AI crawlers, never called; the old code downloaded the latest PDF there) and the Europe PMC copy
  has no version: `SOURCE-UNAVAILABLE` with that reason, no fallback to Europe PMC or Unpaywall; the verifier reads that version's
  abstract through the gateway.
- Europe PMC full text only when the article was first published before T (unknown date -> refused); Unpaywall: arXiv copies pinned as
  above, PMC copies under the Europe PMC rule, publisher copies only when published before T, never an unpinned arXiv / bioRxiv URL.
  Europe PMC and publisher texts carry a `warning`: the open-access text may be a later corrected version.
- No version before T -> `REFUSED` with the reason, nothing downloaded. Cache keyed by identifier and T: a copy fetched for another T,
  or before this rule, is deleted by the fetcher and never read back by `verifier.load_sources` (new `T` argument).
- Live (copy, uid 1000): 1706.03762 at T 2017-06-15 -> v1 of 7 (LaTeX, "41.0" BLEU of v1); 10.1101/2020.03.22.002386 at T 2020-03-25 ->
  v2 (2020-03-23) of 3 named, no full text; no T -> REFUSED.
- Tests: new `tests/test_fetch_fulltext.py` (7, offline, transport stubbed); 16 offline files green.

## v0.4.5, 2026-10-28 - finish_run tool, injection hardening

### Packaging changes (tested, not measured)
- `tools/finish_run.py <dir> [--T] [--plugin] [--offline] [--rw-csv]`: every mechanical end step in one command, in order:
  `validate_card.py --header`, `validate_result.py`, the mechanical retraction check of the plugins (now implemented: Crossref
  `updated-by` / `update-to` and `filter=updates:`, Retraction Watch entries served by Crossref, optional RW CSV; states
  retracted / concern / erratum / none / unknown, `unknown` never turned into `none`; polite HTTP through `gateway.fetch`, cache in
  `<dir>/state/cache`; writes `retractions.json`), `law_checks.py` for a law run, `export_report.py --pdf --open`, `export_data.py`.
  Each step ok / problems / skipped (why), none stops the others; exit 0 only when validation passed; produced paths printed.
  Available, not yet in the instructions (next duel): SKILL.md section 8 is unchanged. Tried on copies of the two e2e runs of
  2026-10-28 (cs-ai, law): validation passed, 6 and 4 DOIs checked (none flagged), exports written. Test: `tests/test_finish_run.py`.
- Prompt-injection hardening (code only; audit with 5 planted sources, `tests/test_injection.py`, no model call):
  verifier: fragments are checked against the claim's own source (a verdict naming another source no longer passes FOUND with that
  source's text: INVALID); every top-level JSON object of the answer is read, an object of another `card_id` is ignored, an id given
  twice with different verdicts (a forged block echoed from a source) is kept out and retried, never taken; source texts keyed as the
  reader sees them (`doi:` keys no longer "unknown source key"). Contradictor: model-written fields enter the reread and match prompts
  on one line (no forged "Extracts" or "List" section). law_checks: a fetched full text (`meta.json`) is never read as a gateway
  record, nor a record whose id is not the card's identifier. Role and instruction wording unchanged (candidates for a duel).

## v0.4.6, 2026-10-28 - CS engines: Hugging Face Hub, standards, open proceedings, related works

- cs-ai: `hf-models`, `hf-datasets` wired (Hugging Face Hub, keyless, 500 req/5 min): repo created < T (repos of the 2022-03-02 migration day: dated by a commit < T when T is on/before that day); `read hfmodel:` / `hfdataset:` serve licence, task, datasets, `model-index` eval results (self-reported) and README at the last commit of main dated < T, never today's card (none found -> refused); search shows licence/task only when `lastModified` < T; downloads and likes `as_of: "now"`. Also declared in `code.md`.
- cs-ai: `standards` wired: RFC (rfc-editor `rfc-index.xml` + `.txt`; month < T; `obsoleted_by` / `updated_by` only through RFCs published < T; current status never served; no Crossref recheck of the retroactive RFC DOIs), PEP (`peps.json`; created < T; status, Python version, resolution only from the header of the text at the last python/peps commit before T), W3C (`api.w3.org`, keyless; latest version < T, later versions masked). Items `rfc:`, `pep:`, `w3c:`.
- cs-ai: `proceedings` wired (`access: page`): ACL Anthology (`anthology.bib.gz`; month < T, year-only -> before the year of T, DOI rechecked on Crossref), PMLR (newest volume published < T of ICML, AISTATS, COLT, UAI, CoRL, ALT; volume RSS feed), CVF open access (newest main conferences published < T). Local title search, parsed indexes in `<state>/cs-index/`; `read acl:` / `pmlr:` / `cvf:` = abstract (PDF not parsed).
- Gateway: command `related <id>` (OpenAlex `related_works`, the work dated < T, each related work rechecked like an OpenAlex search result: publication < T then Crossref deposit AND publication < T). `citing` / `references` refuse the new prefixes.
- `tools/config.json` `cs_engines` (pmlr_volumes, cvf_conferences, w3c_lookups, hf_commit_pages): gentleness bounds, named. Hosts stop at once on 403/404/429.
- New id kinds `hfmodel`, `hfdataset`, `rfc`, `pep`, `w3c`, `acl`, `pmlr`, `cvf` in `validate_card.IDS`, `validate_result`, `verifier.ident_of`, `living_diff`, SKILL.md; `export_data` types `standard` and `paper` (conference paper), hfmodel = software, hfdataset = dataset.
- Tests: `tests/test_engines_cs.py` (14, offline). Live probes 2026-10-28 at T 2026-10-26 and 2021-01-01, every engine plus one read each: 210 items, 0 date on/after T.

## v0.4.7, 2026-10-28 - PISTE connector: Judilibre and Legifrance (not yet verified live)

### Packaging changes (tested offline, not measured; no PISTE credentials at release)
- Engines `judilibre` and `legifrance` (`tools/gateway.py`, PISTE block; `plugins/law.md` sections 5-6). Credentials: the pair
  `PISTE_CLIENT_ID` + `PISTE_CLIENT_SECRET` (`key()`, KEYS.md). Without the pair: `{"status": "skipped", "reason": "not_configured"}`,
  0 request. OAuth 2.0 client credentials (`POST https://oauth.piste.gouv.fr/api/oauth/token`, form body, `scope=openid`); token cached in
  `<state>/piste-token.json` (0600) with its expiry, refreshed when fewer than 60 s remain or the credentials change. The pair goes only
  to the OAuth host, the bearer only to `api.piste.gouv.fr`; HTTPS only, no redirect followed, nothing secret in URLs, receipts
  (`requests.jsonl`: host, path hash, status, size, hash), journal or answers. Token 400/401 or API 401 after one fresh token ->
  `key_invalid` (names only), engines skipped for the run; API 403 -> `not_subscribed`.
- `search-judilibre "<q>" [--court cc|ca|tj|tcom] [--chamber civ1|soc|cr...] [--from] [--to]`: `GET /cassation/judilibre/v1.0/search`
  (Judilibre OpenAPI v1.2.5), decision dates bounded to the eve of T on the provider side; barrier on `decision_date` (< T), ids, ECLI,
  appeal numbers, title; editorial metadata masked when the decision was updated on/after T. `read judilibre:<id>`: `GET /decision`,
  text head + operative part (zone `dispositif`, else the last "PAR CES MOTIFS"), links dated before T; `forward` dated before T with a
  setting-aside solution -> `set_aside_by` (law_checks rule 4).
- `search-legifrance "<q>" [--fund code|loda|jorf]`: `POST /dila/legifrance/lf-engine-app/search`, `CODE_DATE` + `LODA_DATE` with
  `DATE_VERSION` = the eve of T (JORF: publication and signature dates < T); "article N" -> exact `NUM_ARTICLE`. `read legi:LEGIARTI...`
  (`/consult/getArticle`, version in force on the eve of T among `articleVersions`, end exclusive), `read legi:LEGITEXT...`
  (`/consult/legiPart`, date = eve of T), `read jorf:JORFTEXT...` (`/consult/jorf`). Records: `valid_from`, `valid_until` (exclusive;
  an end on/after T masked), `legi_state` on the eve, `version`, `access: api`, tier `primary`, order `FR`.
- `law_checks.py`: ids `judilibre:`, `legi:`, `jorf:` (forms, kinds); `in_force_at_date` uses the LEGI exclusive end. Prefixes added to
  `validate_card.IDS`, `validate_result.FORMS`, `verifier.ident_of`, `export_data` (case / legislation). `check_keys.py`: PISTE pair
  wired and passed (suggestible when the question matches). Gateway: engine filters through `FILTER_OPT`; CLI `--chamber`, `--fund`.
- Tests: `tests/test_engines_piste.py` (12 offline tests: token shape, cache and expiry, no secret anywhere, redirect and host refusal,
  skipped with 0 request, key_invalid on 401, not_subscribed on 403, barrier per engine, version at the eve of T with exclusive end,
  operative part, law_checks on a Legifrance record); `test_check_keys.py`, `test_gateway.py`, `test_validate_result.py` updated for the
  wiring. Live: only the key-less path was run (skipped, 0 request); the authenticated path awaits credentials.

## v0.4.8, 2026-10-28 - setup_keys: install and check a key in one command

### Packaging changes (tested offline; live: absent key and fake NCBI key only)
- `tools/setup_keys.py [NAME] [--check | --remove]`: without a name, lists the keys (check_keys catalogue + contradictor providers,
  present/absent, what each unlocks) and asks which one; `NAME` = variable in any case or a short name derived from it (`piste`,
  `openalex`, `ncbi`, `github`, `swh`, `openrouter`, ...). Value typed with `getpass` (PISTE: Client ID then Client Secret), or read
  from stdin one per line when not a terminal; stripped, written to `~/.config/vp/<name lowercase>.key` (dir 0700, file 0600,
  atomic). Never printed nor logged. Then one LIVE request per source through the gateway's own paths (gateway.fetch for OpenAlex
  and PubMed, CodeSearch/Provenance for GitHub and Software Heritage, the PISTE token + `search_judilibre` / `search_legifrance`;
  a free GET for a contradictor key: `check_url`, else `<url>/models`), one plain line per source: `OK`, `key refused`,
  `identifiers accepted but the application is not subscribed to this API (piste.gouv.fr > Applications > tick <API>)`,
  `not installed`. Exit 0 ok, 1 check failed or not installed, 2 usage. Declared keys with no wired engine: written, no live check.
- `tools/config.json` contradictor providers: `keys_url` (where to get the key) and `check_url` (OpenRouter `/api/v1/key`).
- Fix (`tools/gateway.py` KEY_REJECTED): NCBI answers a mistyped key with 400 "API key not wellformed" (measured 2026-10-28), not
  only "API key invalid"; the old marker missed it (5 retries then PubMed failed). Both now drop the key for the run, `key_invalid`.
- `check_keys.py` text, KEYS.md (new "Installing a key" section, table column) and README point to `setup_keys.py <NAME>` first,
  the manual file method second. Tests: `tests/test_setup_keys.py` (7, offline, stubbed network and input, temp HOME).

## v0.4.9, 2026-10-28 - finance data: DBnomics and FRED/ALFRED

- Gateway: two finance data engines (`plugins/finance.md` sections 7-8). Rule for series: an observation passes only when its period ENDS strictly before T (year, quarter, half, bimonthly, month, ISO week, day; FRED period starts converted by frequency, weekly +6 days; unknown form dropped and counted).
- `dbnomics` (keyless, level-2 pacing 2 s, stop on 403/429): `search-dbnomics` (datasets, then matching series of the best `data_series.dbnomics_datasets`), `read dbnomics:<provider>/<dataset>/<series>` (last `data_series.obs_max` observations before T, provider `terms_of_use`). DBnomics serves CURRENT values: every value carries `as_of: "now (revised values; first releases not available)"`, `vintage: null`, and a `caveat` (no release date: a period ending before T may have been released after T; measured: HICP December 2019 kept at T 2020-01-01). `indexed_at` is the last re-indexing, shown as `last_reindexed`, never a barrier.
- `fred` (`FRED_API_KEY`, `api_key=` to `api.stlouisfed.org` only): `search-fred`, `read fred:<series id>` at the ALFRED vintage of the eve of T (`realtime_start = realtime_end = eve`, `observation_end = eve`), each value with its `vintage`. Without key: `skipped` / `credential_missing`, 0 request. FRED 400 naming `api_key`: `key_invalid`, 0 request for the rest of the run. Other 400 (no ALFRED history): refusal, never a fallback on current values. `citing`/`references`/`related` not served for data ids.
- `check_keys.py`: FRED wired and passed; `setup_keys.py fred` checks the key live. New id prefixes `dbnomics:` and `fred:` in `validate_card.IDS`, `validate_result`, `verifier.ident_of`, `export_data` (type dataset). `tools/config.json`: `data_series` (obs_max 240, dbnomics_datasets 3).
- Docs: `plugins/finance.md` (sources block, sections 7-8, verification 3), KEYS.md (FRED row, key rules, finance without key), README wired list.
- Tests: `tests/test_engines_finance.py` (9, stubbed transport); `test_setup_keys.py` (FRED OK / refused); `test_validate_result.py` (new ids). Full offline suite green as uid 1000. Live 2026-10-28: DBnomics search and read at T 2026-10-26 and 2020-01-01 (no period >= T); FRED without key (skipped, 0 request) and with a fake key (key_invalid, `setup_keys` "key refused"). Not yet verified live with a real FRED key.

## v0.5.0, 2026-10-28 - one source = one file (registry, template, contributing guide, contract test)

- **Sources in `tools/sources/`, one file each** (31 source files, 25 gateway engines + 6 code commands; a family shares a file only when it shares code: `piste.py` Judilibre + Legifrance, `biorxiv.py` bioRxiv + medRxiv, `hal.py` hal + hal-info, `hf.py`, `standards.py`, `proceedings.py`). Each file exposes `SOURCE`: engines or code commands, identifier prefixes (result form, law form, export type), read and chaining, plugins, access level, terms, barrier notes, `as_of`, hosts (pacing, stop codes, timeout), optional key spec (variables, how sent, allowed hosts, link, free/paid, live check, rejected-key markers). Shared helpers: `_common.py` (fetch, Barrier, date helpers, key resolution), `_cs.py`, `_series.py`.
- **Registry** (`tools/sources/__init__.py`): validates every declaration and refuses duplicate names, engines, commands, prefixes, and conflicting host settings (`RegistryError`). Derived from it: gateway `ENGINES` / `CODE_ENGINES` / `SERVED_BY` / `FILTER_OPT` / `INTERVAL` / `STOP` / `TIMEOUT` / key rules and read / citing / references / related routing; `check_keys` `CATALOGUE` / `SUGGESTION`; `setup_keys` labels, prompts and live checks; `validate_card.IDS`; `validate_result.FORMS`; `verifier.ident_of`; `export_data.kind`; `law_checks` law prefixes, forms and decision / text prefixes.
- **User sources** (opt-in): `~/.config/vp/sources/*.py`, loaded only with `VP_USER_SOURCES=1`, announced on stderr (and `user_sources` in `sources`); a directory present without the flag is reported, not loaded.
- **Added**: `tools/sources/_TEMPLATE.py`, `CONTRIBUTING.md` (barrier rules, access policy, keys, tests), and `tests/test_sources_contract.py` (12 tests over every source: complete declaration, unique names and prefixes, plugin `access:` = declaration, key hosts declared, prefixes routed, 0 request to key hosts without the key, fake key never leaked and sent only as declared, user sources opt-in, template valid). README / KEYS: "Adding a source" pointer. SKILL.md: Inventory line only.
- **Behaviour unchanged**: same engine names, commands, options, JSON outputs, receipts, journal, cache keys, pacing and key handling. `gateway.<name>` compatibility kept for every former function or constant (`gateway.fetch = ...` / `gateway.STATE = ...` reach every source). Checked: the 22 existing test files green, unchanged (207 tests; 219 with the contract test); `check_keys.py` (text, JSON, suggest) and `setup_keys.py` (listing, unknown name, checks) outputs byte-identical, with and without keys; derived tables, identifier kinds, forms and export types identical to v0.4.9 (only difference: OpenAlex's stop on 429, formerly special-cased in `fetch`, is now declared in `STOP`, same effect); `--help` and offline refusals identical. Live, from copies at T = 2026-10-26 with fresh state dirs (pubmed, crossref, arxiv, openreview, eurlex, justice-administrative, dbnomics search + read, versions, sources, fred and judilibre without a key): v0.4.9 run just before and v0.5.0 identical, cache keys and journal included. The only difference was the 4th EUR-Lex hit, which alternates between two judgments of the same day: two v0.4.9 runs also disagreed.

## v0.5.1, 2026-10-28 - real verification at bounded cost, cited passages, robust tool calls

Adopted after two duels (protocols frozen by sha256 before the first paid call): mechanics duel, 5 cases x 2 arms against v0.5.0
(compliant runs 5/5 against 0/5; precise supported claims 178 against 110; claims lost to the shared call cap 0 against 37; put on hold
for cost, median x2.86), then a confirmation run of this configuration (full text off by default) on the two costly cases: median
cost ratio over the five cases 1.63 (threshold 1.8), 2/2 runs compliant, no abandon. Limits: n = 2 new runs for the confirmation,
one judge family for its error rate; legal texts stay the most expensive case (x2.86, the verifier reads long decisions whole).

### Verifier
- Own call budget: the verifier's gateway readings use their own pool (`verifier.call_cap`, default 60; counter
  `state/counter-<run>.verifier.txt`; `calls_per_pool` in `run.json`). A search cap already reached no longer turns claims into
  SOURCE-UNAVAILABLE (v0.5.0: up to 77 % of a report's claims). Sources are read in order of the claims they carry.
- No model name fixed: `verifier.model` is empty = the host CLI's default (`--model` / `VP_MODEL` override).
- Optional, off by default: `--fulltext` reads the open full text pinned before T (`verifier.fulltext`, `verifier.fulltext_cap`);
  measured to multiply the verifier's cost (up to 9 USD-equivalent on a 12-paper report). `--windows windows` sends only the
  code-chosen windows of long sources (exact substrings; ABSENT on windows is judged again on the whole text); not yet validated
  with a model (one replay: -40 % cost on a legal case but 9 claims left UNVERIFIED), so `verifier.windows.mode` stays `whole`.

### Cited passages
- New `tools/passages.py`: under each reference of REPORT.html, the claims checked against it with the exact source sentence
  (verified fragment highlighted, origin: full text or record + abstract). Shown only when the fragment is found in the text the
  verifier actually read: an invented quotation never appears. Also `passages.json` and `PASSAGES.md`. REPORT.md is unchanged.
  On the nine runs of the earlier duel: every FOUND or DISTORTED claim gets a passage (288 of 488), none inexact.

### End of run and tool calls
- `finish_run.py` is the end command (SKILL.md section 8): validation, retraction check, law checks, exports; it writes a receipt
  `state/finish_run.json` and `validate_card.py DIR` refuses a gateway run without a fresh receipt (check 13).
- `--plugin` takes a path, `plugins/<d>.md` or a bare `<d>`; the tools run from any directory; one-line errors, no traceback.
- SKILL.md section 0: one script per Bash call (no `mkdir`, `&&`, `;`, pipes or heredocs), retry a denied call once in the bare form,
  never stop on a denial (without it, 6 runs of 6 stopped at the first denied compound command).

### Tests
- New `tests/test_run_mechanics.py`, `tests/test_passages.py`, `tests/test_windows.py`; full offline suite green as uid 1000.
