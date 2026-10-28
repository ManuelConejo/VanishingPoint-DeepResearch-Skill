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
  plugins/code.md "Contradictor after the report"): optional, absent by default. A model of another family than the author (`codex` through the
  Codex CLI on a Claude Code host, `claude` through `claude -p` on a Codex host, `kimi` or `gemini` through OpenRouter, optional) reads the report, Y and X without tools and claims at most 3 false statements
  and 3 misses with references; mechanical check, exclusivity call, fresh-context rereads with the cited extracts only;
  `contradictor.json` is applied by the orchestrator (annotation "contradicted by <family>", added findings verified like any other).
  Measured on our benches on the 6 code reports of the whole-reading duel, frozen protocol and criterion: every family adoptable
  (cases with a true detection 6/6 each; true detections against added errors: Gemini 14/11, Kimi 20/6, Codex 20/8); the measure
  cost 6.95 USD; in use about 0.26 USD per contradictor call and 0.6 USD of rereads per report.
- Known limits, stated in the plugin: n = 1 per cell; one reread model for every family; 36 of 37 misses confirmed by that reread;
  exclusivity judged by two other families on our benches and by the host model in the product; the contradictor prompt is the
  measured text with English JSON keys, the reread and match prompts are English translations of the measured French texts
  (same rules, same answers), not re-measured after translation; `claude` as contradictor (Codex host) and anything outside the code plugin not measured.

### Packaging
- `check_keys.py` prints the configured contradictor families (names only, and whether `OPENROUTER_API_KEY` is present) before the
  mode line; `KEYS.md` documents `OPENROUTER_API_KEY`; `tools/config.json` gains a `contradictor` block (families, measured
  models, caps, reread model per host profile).
- Tests: `tests/test_contradictor.py` (fake OpenRouter endpoint, fake Codex and claude executables: no network, no cost),
  `tests/test_check_keys.py` extended.
