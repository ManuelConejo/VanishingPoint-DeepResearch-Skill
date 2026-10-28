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
