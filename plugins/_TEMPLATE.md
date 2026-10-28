# Plugin <discipline> - <title> (<date>)

Empty template. Copy it to `plugins/<discipline>.md` and fill the four sections **in this order and under these exact titles**: the engine reads them by their title. Nothing invented: every source says where its facts were established (documentation URL, probe date); information that was not established is written "not established", never a guess. Every key is OPTIONAL: without a key, the source is skipped with a receipt (`credential_missing`), never "nothing found". A new plugin does not touch the engine; it is tested on 2 questions of its discipline.

## Sources

Block read by `tools/gateway.py` (exact format: README.md, "Where to put a plugin"). Declare **all** the engines of the table below, wired or not: an engine that is not wired is listed `not_wired` and refused cleanly, it breaks nothing.
```sources
engines: <e1>, <e2>                      # required ; wired: pubmed, europepmc, crossref, openalex, arxiv, eurlex, justice-administrative, hal, theses-fr
since: <YYYY>                            # optional: lower bound (year)
cap: 60                                  # optional: safety cap on calls
keys: <VARIABLE_1>, <VARIABLE_2>         # optional: resolved by key() (env NAME, ~/.config/vp/<name in lowercase>.key ; KEYS.md), never required, never displayed
useful_when: <e1>=<when this free-key source would probably have brought something: words of the question> ; <e2>=<...>   # optional: one entry per FREE-key source (never paid nor under a restrictive licence) ; read by tools/check_keys.py --suggest (lexical matching, at most 2 suggestions per run)
access: <e1>=api, <e2>=page              # required: access level of every declared engine (ACCESS-POLICY.md) ; the gateway applies level-2 pacing to `page`
disabled: <e3>=tos_forbidden, <e4>=technical_block   # optional: sources listed but never called, with their reason
```

Common date bound: provider-side filter at the day before T, then local re-check (every known date < T; a partial date counts as its upper bound). For each source, the seven fields below:

1. **<Source name>** (<what it covers>) - `access: <api | page | browser | tos_forbidden | technical_block>`
   - Access: `api` (level 1: documented API, used under its terms; robots.txt has no effect); `page` (level 2: public page, even under `Disallow`; 1 request / 2 s / host, declarative UA with contact, cache, stop on 429/403); `browser` (level 2b: public page behind a JS challenge, driven browser, same pacing); `tos_forbidden` (terms of service forbid automation or AI use: listed, disabled, exception only by a written decision of the owner); `technical_block` (restricted access: account, paywall, captcha, registered IP: listed, disabled, reason written). Reference: `ACCESS-POLICY.md`.
   - Endpoint: `<URL or endpoint>`
   - Query: `<parameters, syntax, pagination, page size>`
   - Date bound: <yes: parameter and re-checked field / no / not established>
   - Key: <none / OPTIONAL: variable name, location of the copy, never displayed; behaviour without key>
   - Rate: <published limit, verified, or "not established"; local interval; conduct on 429>

2. ...

Set aside, disabled: <source - measured or observed reason; marking `tos_forbidden` or `technical_block`>.

## Discipline biases

Feynman form: one line per bias, the observable signal that triggers it, the reference; signals, never verdicts. Shared vocabulary: the ids of the shared catalogue `vp-bias-catalogue/1` (`ai.*`, `fin.*`, `bio.*`, `law.*`, `code.*`); for a new discipline, create its catalogue in the same format (`[[bias]]`: `id`, `name`, `definition`, `signals`, `judge_question`, `severity`, verified `refs`) and say whether it is measured or not.
- Shared catalogue: `<name>` (<n> biases, measured / not measured).
- **<Bias>** (`<prefix.id>`): <observable trigger> (<where observed, measurement>).
- ...
- To be completed by <whom>.

## Output format

The report (`REPORT.md`, SKILL.md section 5) keeps the eight sections of the output contract; the plugin only says what a **finding** of its discipline argues (the four steps, the verdict scale) and what the **machine annex** (SKILL.md section 6, last short call) contains beyond `card.json` and `result.json`. One annex entry per <unit: study, mechanism, decision...>, fields in order (common format: the `card.json` schema checked by `tools/validate_card.py`):
1. **Full citation**: <identification fields specific to the discipline>.
2. **Claim** (A1, A2...) decomposed: <elements: subject, comparator, condition, figure and unit, direction, scope, certainty, causality>.
3. **Figure**: value, unit, where in the source, `checked` if re-read.
4. **Protocol**: <what the discipline requires: period, sample, runs, baselines...>.
5. **Discipline-specific fields**: <...>.
6. **Verified status**: metadata verification codes, level-1 verdict per claim.
7. **Dates**: dates of the source, T, `before T` / `excluded`.

At the end of the report: receipt of the sources (consulted, accepted, rejected with reason, quotas reached), exclusions by date.

## Verification rules

Level 1 (`tools/verifier/ROLE.md`, the level-1 verifier role; fragments checked by `tools/verifier/citation_check.py`), never as a collection filter. Rule shared by all plugins: **mechanical retraction check** (Crossref `has-update` / `update-to`, Retraction Watch; no model call; `unknown` never converted to `clean`; to be wired into `tools/verifier.py`). In addition, specific to the discipline:
1. <rule: what the verifier checks in addition, and the verdict it returns when it is missing>
2. ...

<!-- Extra sections specific to the plugin (e.g. "Context capsule", "Modes" in code.md): after the four fixed sections, never before nor between them. -->
