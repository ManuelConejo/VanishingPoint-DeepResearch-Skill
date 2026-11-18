# Frontier

A skill for Claude Code and Codex that helps a researcher advance **one** research idea: prior art and raw materials, competing hypotheses, 1 to 3 minimal tests designed by strong inference, a critique of the test protocol by another model family, optional execution in an isolated container, a one-page idea card (`IDEA-CARD.md`) and an append-only decision log. The agent instructions are in `SKILL.md`.

Frontier lives in the VanishingPoint (VP) repository, in `frontier/`, and uses VP when it is installed next to it (prior-art mode, contradiction hunt, verified references, contradictor). Without VP it still works, with the host's own search, and every card then starts with "References not verified (VP not installed)".

The checks of `tools/check.py` are structural: they check that every box of the protocol is filled, consistent and traceable (fingerprints of the protocol frozen before the result, simulations rerun, VP verdicts and gateway journals, dates before T, the critic's raw answer), not that the science is right.

## Status and known limits (read before use)

This is a pilot release. It has not been validated: the V1 pilot has not been run yet, and no result of it exists.

- **Execution is disabled by default** (`config.json` `"execution_enabled": false`). Tests are delivered as plans. The container path (`tools/run_test.py`) has never run on a real Docker or Podman engine; hard links, the size of `output/`, the race between the path check and the mount, SELinux labels and rootless Podman are not handled. Turn it on only deliberately (`"execution_enabled": true`, or `FRONTIER_EXECUTION_ENABLED=1`) and at your own risk.
- **The checks are structural.** `tools/check.py` checks that fields are present, consistent and non-trivial; it does not prove scientific soundness. A trap filled with plausible but empty text passes.
- **Proofs are consistency, not provenance.** Fingerprints, the decision log, the raw critique and even a VP run directory can be written by the host itself; Frontier checks that they agree, not who wrote them or when.
- **References (what is and is not checked).** With VP, `check.py` checks that each reference id appears in `card.json`/`verdicts.json` of a cited VP run with a status other than ABSENT or INVALID, and that a VP prior-art file (`PRIOR-ART.md`) is given. It does NOT check: that the verdict's source is the same source as the card's claim; that `PRIOR-ART.md` belongs to one of the cited runs; what a reference "says" against the source fragments; the wording of a DISTORTED claim after correction. This is a consistency check, weaker than VP's own verification.
- **Date barrier.** With VP, the barrier is the one of VP's gateway (it serves only documents dated before T); `check.py` only checks that every gateway call of a cited run carries a T not later than the idea's T. Frontier's own date check is at the YEAR level: a reference of the same year as T, or with no known year, passes silently. Without VP, references are not verified (the card says so) and the date barrier is declarative.
- **Critique independence is not proved.** The critic family is declared in `config.json`; on a host without another model family, the card says "same family".
- **Fixed labels of `IDEA-CARD.md` are in English**; only the prose follows the user's language.
- **Cost** is usually "unknown" (the host does not report it). **Python 3.9 and macOS** have not been run (3.9 syntax is checked; the code avoids Linux-only paths).

## Install

1. Copy this `frontier/` directory into your skills directory:
   - Claude Code: `.claude/skills/` of a project (`.claude/skills/frontier/`) or `~/.claude/skills/frontier/`;
   - Codex CLI: `~/.codex/skills/frontier/`.
   To use VP, either keep `frontier/` inside the VP repository (VP is then found as `../SKILL.md`), or set `FRONTIER_VP_DIR=/path/to/vanishingpoint`, or write that path as `"vp_dir"` in `frontier/config.json`.
2. From the skill directory, run `python3 -I tools/setup.py` (or `python3 -I tools/setup.py --check` for a read-only check, `--json` for machine output). It checks Python (3.9 or later), creates `frontier/.venv` only if `requirements.txt` lists packages (none in this version), detects VP, and detects docker or podman (the container probe runs only when execution is enabled).
3. Optional, in `config.json` (or the environment): `critic.host_family` (`FRONTIER_HOST_FAMILY`), the family of the model that runs Frontier; `critic.families` (`FRONTIER_CRITIC_FAMILIES`, comma-separated), the families available as critics of the protocol; `critic.aliases`; `search_model` (`FRONTIER_SEARCH_MODEL`), the model of the sub-agents; `run_limits` (memory, CPUs, processes, non-root user, output cap of the container; `"user": "host"` runs the container as your own uid:gid, never root, when the default unprivileged user cannot write `output/`); `budget` (per idea: 3 VP runs, 1 critique, 1 execution). No family or model is written in the code.

Nothing is installed outside the skill directory. Frontier never installs a container engine and never pulls an image: for the optional execution step, install Docker or Podman yourself and pull the probe image named in `config.json` (`probe_image`, default `busybox:latest`) and the images your tests use. Environment variables defined by an image itself are not controlled by Frontier. Without an engine, tests are delivered as plans ("plan only").

Requirements: Python 3.9+ standard library only; macOS or Linux.

## Tools

V4 adds two small records after the existing research and critique. The host
records one weakest inference and one revision (or reasoned no change) in
`test_revision.json`, with one targeted VP search or an explained skip and
explicit H1/H2/H0 role predictions. `tools/overlap.py DIR` derives
`overlap_ledger.json` from local VP journals and closest-work assessments:
query, returned overlap, dimension and unresolved difference. The card gets
one line for each; the report keeps the details. Missing records/differences
are `[REVISION]` / `[OVERLAP-LEDGER]` marks, never a novelty verdict or veto.
Older formats remain accepted; writing either V4 artifact enables the new
summaries on historical cards. See SKILL.md §§1 and 4 for the exact fields.

| Tool | Role |
|---|---|
| `tools/setup.py` | bootstrap and self-check (`--check`, `--json`) |
| `tools/new_run.py` | creates `frontier-YYYY-MM-DD-<subject>/` under `--parent`, never an existing directory |
| `tools/check.py` | structural validation of a working directory against `schemas/*.json` and the rules of `SKILL.md` |
| `tools/sim.py` | sensitivity simulation (two arms, means or proportions, or paired), fixed seed; rerun by `check.py` |
| `tools/pack_critique.py` | material for the critique of the protocol (prompt, or a directory for VP's contradictor); `--receipt` for the critic's raw answer |
| `tools/run_test.py` | runs one test in docker/podman: local image only, `--network none`, read-only, resource limits, non-root, no environment passed, no symbolic link, capped output |
| `tools/card.py` | assembles `IDEA-CARD.md` from the JSON files, after `check.py`; never writes an invalid card |
| `tools/log.py` | append-only decision log (before / after); a "before" freezes the protocol's fingerprint |
| `tools/step.py` | one entry per step in `run.json`: cost and duration ("unknown" when the host gives nothing), budget per idea |
| `tools/export_judge.py` | blind export for the judges of the V1 pilot (0-6 grid), from a working directory or a baseline |
| `tools/rebound.py` | mechanical aid of the rebound step: duplicate groups, quotas, `IDEA-TREE.json` (register, check), the researcher's choice, links to child ideas |
| `tools/export_rebound.py` | blind export of the three-arm rebound pilot (A Frontier, B model + VP without operators, C model alone) in one uniform format; the order is drawn with a secret seed written only in a separate key file (`--key`); `notes` registers the researcher's own ideas (time and sha256) before the lists are read; `stats` computes the written stopping rule |
| `tools/history.py` | step "Already tried here": local search of the user's own project archives (`intake.json` `project_dirs`) for the terms of the idea, the tests and the neighbouring ideas; writes `history.json` (file:line, short excerpt, verdict markers in French and English, reopening condition); never reads the network |
| `tools/hybrid.py` | step 0-ter, the free draft: lists what `free_draft.md` holds that must be verified, marked "unverified (memory)" or removed (`scan`), writes a starting `draft_claims.json` (`stub`) |
| `tools/context.py` | step 0-quater: candidate key numbers (periods, headcount, information coefficient, costs ...) found with `file:line` in the README, result and lesson files of `project_dirs` (`extract`), confirmed (`confirm`) or given by the user (`add`) into `intake.json` `context` |
| `tools/matter.py` | step 1-bis: existing code, datasets, benchmarks (`search`, `repo`, `add`, `none`), optional local sources (`optional`) and the moment of the subject (`moment`), all through VP's gateway |
| `tools/gwclient.py` | runs VP's gateway as a sub-process (never a network call of Frontier's own) and saves each answer as an envelope under `matter/` |
| `tools/catalogue.py` | OPTIONAL: creates and incrementally updates a catalogue of methods for one domain through VP's gateway (`create`, `ingest`, `update`, `check`); mechanical implementability score |
| `tools/common.py`, `tools/schema_lite.py` | shared helpers; the small JSON-schema validator |

## Hybrid work, project context, expected effects, matter and moment (AM1 round)

- **Free draft first** (`free_draft.md`, `draft_claims.json`): the host writes what it knows with no format, then each claim and reference the card takes up is verified through VP, marked `unverified (memory)` or removed; `tools/check.py` refuses an item of the draft that is taken up with no claim to cover it ([DRAFT-UNMARKED]). The detection (author-year references, identifiers, decimal numbers and percentages) is a net: a claim it cannot see (an integer quantity, a claim in other words) is still the host's to settle.
- **One page and a full report**: `tools/card.py` keeps `IDEA-CARD.md` within one page and writes `IDEA-REPORT.md` beside it, rendered from the same files with nothing clipped; `tools/check.py` refuses a report that is stale or edited by hand.
- **Context**: `intake.json` `context` (objective, data, constraints, key numbers). `tools/sim.py --context <dir>` uses the confirmed numbers and the output says what came from the project and what did not; `tools/sim.py --needed-n` computes the test size for an effect. The tree of ideas lives in `config.json` `tree_dir` (or `FRONTIER_TREE_DIR`) so that it persists across sessions.
- **Expected effects** (`evidence_table.json`): source, sample, measured effect, replication (yes, no, unknown) and the needed test size for each main lead.
- **Matter and moment** (`material.json`, `moment.json`): code, licence, last activity, datasets, benchmarks found live through VP's gateway; the moment (rising, saturating, revived, unclear) read from dated publication totals. The optional catalogue (`config.json` `catalogue` or `FRONTIER_CATALOGUE`) and the optional directions index (`directions_index` or `FRONTIER_DIRECTIONS_INDEX`) are skipped, and the report says so, when absent.
- **Limits.** Everything here was tested against a simulated gateway, never a live one: the exact shape of the real gateway's `repo-info`, `find-implementations` and `search-hf-datasets` answers is assumed (tolerant extraction, `tools/matter.py extract_*`), and the real journal of the gateway does not record totals, which are therefore checked in the saved answer. The "moment" counts describe an index, not the truth, and the reading rule is a fixed heuristic with thresholds in `config.json` `moment`. The directions index is read as a TSV with a `direction` column (an assumed format). The catalogue's date of last update is kept in a `.meta.json` next to the table.

## Round 3: a bare idea, an honest card

Directories made by `tools/new_run.py` carry `frontier-version.json` and are held to the round-3 rules (`SKILL.md`, section "Round 3"); older directories keep their former checks and card, except the outgoing guard and the arithmetic of strata and periods. What changed, in one line each:

- **Nothing leaves before the guard** (`tools/guards.py`, called by `tools/gwclient.py` before the gateway starts): an explicit short list of allowed requests (the words of the idea), refusal before sending, no archive or draft text, no archive-only word; a refusal logs a hash, never the text.
- **Provenance**: the authority is the gateway journal written by VP; a value the journal does not bind is "unverified provenance", never shown as extracted; a journal field that contradicts a saved answer is `[PROV-MISMATCH]`.
- **A complete card**: no ellipsis, no "(+k more"; what decides is whole; a "Tomorrow" block of five lines; scenarios are labelled, never a result. On success, the first two lines of `card.py` stdout are the card and report paths, followed by the reminder to run it last after input edits. Read the first line for one path or the first two lines for both; do not require an exact total line count.
- **Short draft items and uncertain reuse**: the v2 stub keeps short textual leads and labelled values such as `Accuracy: 90 %`, with the existing `{id, quote, status}` entries and draft hash. Bare numbers, unit-only fragments and headings are excluded. Strict scans separate exact whole-quote reuse (`taken_up_in`) from possible lexical reuse (`possible_reuse_in`). Partial matches carry advisory `[DRAFT-REUSE?]` marks even when the source quote is verified; matching words and numbers cannot establish agreement. Review the whole draft for paraphrases the lexical net cannot see.
- **Partial returned IDs**: the overlap ledger keeps valid IDs and their query attributions in incomplete lists. `returned_ids` remains a list for known or partially known results, `null` for fully unknown results, and `[]` for known empty results; `ids_complete` exposes completeness. One advisory issue counts fully unknown and partial queries separately, with per-run counts. Historical saved ledgers and reports may need regeneration after this representation change.
- **Test validity**: arithmetic checks (`[ARITH-*]`), a correction is "fixed" only with a checked proof and a second critique (`critique2`), data already seen cannot confirm, verdicts carry their scope.
- **Realistic power**: parameters measured (with a source) or assumed (as ranges); `tools/sim.py robust` replays the test under the null and the useful effect with perturbed noise, dependence and overlapping observations.
- **Targeted evidence**: `decisive_claims.json` (fragment, scope, limits, support), search coverage from the VP journal (never a recall), a free draft verified in the order of what decides.
- `tools/export_compare.py`: the template of the blind, equal-budget comparison of Frontier against the model alone on several bare ideas (A9). It prepares and tallies; the comparison itself needs models and a judge and has NOT been run.

Limits of round 3. The real VP journal records the number of results and the identifiers, but probably no digest of the answer and no index total: against such a journal the provenance of a value stays "unverified" (the code attests only what the journal binds; VP is not modified). The outgoing guard is lexical: a query made only of words of the idea that still encodes archive content in its choice of words is not seen; words of fewer than four letters are not compared with the archives. The arithmetic checks read only the patterns they know (a number of strata beside a date range and a "month x tercile" factor; "N months/years/quarters" next to a range of years). The power simulation covers series designs (a HAC analysis of paired differences), not proportions, and it cannot judge whether an assumed range is plausible. Lexical nets (`[SCOPE]`, `[RECALL-CLAIM]`) are nets, not proofs. `tools/catalogue.py` still has no pagination: a query that reaches its cap is reported and `updated` is not moved when nothing new is seen, but works beyond the cap are not fetched. Nothing was run against a live gateway, a live catalogue or a real index.

## Frontier v2: the path

Directories made by `tools/new_run.py` now carry `{"frontier_version": 4}` and follow the v2 path (`SKILL.md`, section "Frontier v2: the path"), which includes every round-3 rule. The rule of v2: **the free phase opens, the rest verifies; only factual, arithmetic, integrity and confidentiality errors block, everything methodological is marked** (`mark: [CODE] ...`, and "Marked, not blocking" on the card) and nothing is removed. In one line each:

- **Approved framing** (`tools/framing.py`, `framing.json`): after the free phase the agent restates objective, success criterion, constraints and what would refute the idea; the user approves or corrects in one reply; an absent user means an assumed framing, marked "ASSUMED". `tools/step.py` refuses the work steps before it.
- **Prior art by an iterative research plan** (`tools/research.py`, `research_plan.json`): fields to question, keywords per field, 2 to 3 rounds of plan, search through VP's gateway (guarded before sending) and revision; four outcomes (Exists, Partially, Not found, Insufficient search) backed by a verified passage; coverage shown, recall never claimed, no novelty note.
- **Rivals and facets**: facets of the idea, every rival and variant made by a named operator (recurring ingredient, or "operator not measured"); named datasets, models and metrics recorded with how their existence was checked (`tools/named.py`, `named_elements.json`): verified, checked by the host, unverified, or NOT FOUND, never silently dropped.
- **Tests ranked by information over cost**: `belief_shift` (what each outcome does to the belief between the competing explanations, in scenarios, without a probability) and `voi` (ordinal information and cost); the simulation uses the project's numbers or the card says which ones are missing.
- **Restitution**: a "Next step" block on top of the card (first step, inputs, cost, stop rule), nothing truncated, a "fixed" correction without proof shown "claimed fixed, not proven".
- **Rebound by iterative search**, at most 2 ideas per operator, prior art on all; a trial the project classed is said at the head of the test or idea.

Limits of v2. Nothing here ran against a live gateway, a real index or a model: the tests use a simulated gateway. The word-sharing net for classed trials (`[HISTORY-NET]`, three shared content words) is lexical and can miss or over-flag. The ordinal "information over cost" levels are declared by the agent, not measured. `tools/named.py` can verify a dataset only through an item found by the gateway or through a verified VP fragment; for models and metrics the host usually records "checked by the host" or "unverified". The four methods of the ten discovery methods of the Nova paper that are not listed in the project notes are not in the operator library. A directory of an earlier round keeps its former card (truncations included): there is no migration tool.

## Already tried here (step 0-bis)

Before any proposal, Frontier looks in the user's own project archives (the local folders named in `intake.json` `project_dirs`) for what was already tried. `tools/history.py` only searches and extracts (md, txt, rst, py, json, yaml files; no `.git`, `venv`, `node_modules`, links or binary files; limits in `config.json` `history`); the terms, the synonyms and every decision stay with the host model. A test or a neighbouring idea that overlaps a passage marked as closed (CLASSED, DO NOT REOPEN, REJECTED, NO-GO ... in French or English) is either removed or kept with `internal_history`: the verdict cited as file:line, the written reopening condition and why it is met now; `tools/check.py` refuses it otherwise ([HISTORY-OVERLAP], [HISTORY-CITE]). With no folder given the step is marked "not checked" on the card.

**Confidentiality.** What is found in the archives stays on the machine: it never enters a VP request or any command that reaches the network, and `tools/check.py` looks for text of `history.json` in the recorded requests ([HISTORY-LEAK]). Limits: a search that finds nothing proves nothing; the overlap rule is lexical (terms and synonyms of the host, a 5-word run for the leak check); a closed trial written with other words, or in a format that is not read (notebooks, spreadsheets, PDF), is not seen.

## Rebound: neighbouring ideas (steps 8 and 8-bis)

After the card, an optional **rebound** proposes 5 to 10 neighbouring ideas (2 to 4 after a test result, step 8-bis), each made by one named operator (facet recombination, analogy, literature bridge, anomaly, revived old idea, hypothesis inversion, morphological analysis) from cited material, with a structured mechanism, hypothesis and one-line minimal test, a prior-art check on every idea before any ranking (Exists, Partially, Not found, Insufficient search; "Not found" is never "new"), feasibility shown only on verifiable elements (else "not established"), and trade-offs. The files are `rebound.json` and `rebound_after.json` (`schemas/rebound.json`); the ideas of the researcher's choice (0 to 2) are kept from one session to the next in `IDEA-TREE.json` (`schemas/idea_tree.json`), by `tools/rebound.py`. There is no novelty score and no model ranking. The prior-art search is registered, not just declared: with VP, one VP run per idea, and every written query must be a query of that run's gateway journal (`state/journal.jsonl`), sent before the check date and before any ranking; a ranking or a choice is refused until every idea has its registered search. VP stays optional: without it the prior-art checks use the host's search, the files carry the header "References not verified (VP not installed)", and the card marks every prior-art line "not verified: no VP". `recurring_ingredient` says that the operator is one of the ingredients found again in independent systems (never an efficacy figure). Thresholds are in `config.json` `rebound` (`prior_art_checks_max` per file, `prior_art_checks_card_max` per card).

Limits: the evidence behind the design comes from abstracts of 46 sources in language processing and machine learning, and no source measured each ingredient alone, so no efficacy figure is claimed; operators other than the first three are labelled "not measured". The duplicate grouping is by words and by structured fields: it flags, it does not decide. The lexical check against rankings in disguise ("best idea", "ranked first") is a net, not a proof. The step has not been validated: the prospective three-arm pilot (`tools/export_rebound.py`; written stopping rule in `SKILL.md`, computed by `export_rebound.py stats`) has not been run, and a pilot with a single judge keeps that judge's bias.

## Pilot V1: judge export and baselines

`python3 tools/export_judge.py <dir> --out <out> --case-id <blind id>` writes `judge.json` and `JUDGE.md`: the idea, the hypothesis statements and the tests reduced to the strong-inference grid, with the six criteria scored 0 or 1 (0-6), and nothing of the outcome (no recommendation, result, decision log, critique, prior art, reference identifier, timestamp or directory name; the export is refused if an outcome text slips into it).

The two baselines of the pilot are written in the format of `schemas/baseline.json`: `"baseline": "T1"` (the model alone, without search) or `"T2"` (one standard VP run on the idea, `vp_run` required, then a recommendation by the same model), with `idea`, `domain`, `T`, `produced_by`, optional `hypotheses`, `tests` (each test in the item format of `schemas/tests.json`) and `recommendation`. `python3 tools/export_judge.py --baseline <file> --out <out> --case-id <blind id>` gives a `judge.json` with the same keys as a Frontier directory, for the paired comparison; `produced_by` and the recommendation never reach the judges. Examples: `tests/fixtures/baseline_t1.json`, `tests/fixtures/baseline_t2.json`. Cost and duration per step are in each working directory's `run.json`.

## License

Frontier is part of the VanishingPoint repository and is distributed under the repository's license, Apache-2.0 (see `LICENSE` at the repository root; there is no separate license file in this directory).

## Frontier v2r2 corrections

The host submits the five most decision-relevant free-draft claims (all if fewer)
to a registered VP card with `tools/hybrid.py submit`, then runs VP verification
and inspects their verdicts. Other claims remain visible memory leads. The tool
does not invent verification or judge which claims matter. A v2 draft with at
least five claims and zero submissions fails check.py; pending verdicts are marked.

V2 uses `card_max_lines` (default 80), shared by the renderer and checker. Every
neighbouring idea and conditional scenario stays on the card. Research detail,
coverage detail and evidence scope text stay complete in IDEA-REPORT.md. Older
run formats retain their rendering and checks. Historical regression excerpts
are labelled as reconstructed where full originals were not supplied.
Tests built on reconstructed excerpts are detector tests (the defect text is in the excerpt by construction), not proof that the original cards had the defect.

Individual rebound critique (step 8, within the optional rebound):
`tools/rebound.py pack <dir>` prints only public idea packets, checked with the
shared tournament packet guard. A separate critic context judges every idea
alone (two objections and one proposed change; no comparison). Record the
whole batch with `record <dir> --critique <file>`, then the author's bounded
statement repairs with `repair <dir> --repair <file>`. Both require the current
`input_sha256` from `pack`. Original statements, identity, prior-art checks and
critiques stay recorded; the card and report disclose routes and same family.
Both mutations refuse after ranking or selection. Every critique follows the
latest prior-art date of all ideas; the tool dates each repair. Critique or
repair dates after ranking block [REB-REPAIR]. Older files without critiques
remain valid with the non-blocking [REB-CRITIQUE] mark; invalid repairs block
[REB-REPAIR].
The extra batch call uses `rebound_critiques_max`, recorded by
`tools/step.py <dir> --step rebound_critique`, separately from the protocol
critique budget. A recorded critique without this journal entry blocks
[BUDGET], like other missing step receipts. See SKILL.md point 8.4 for receipt formats and evidence scope.
This step is part of the rebound, not a separate option; the optional debates
tournament is unchanged.

## English data names

Optional rebound debates use `tools/tournament.py`, `schemas/tournament.json`,
`tournament_rebound.json`, the `tournament` configuration block and `[TOURNAMENT]`
marks. Existing user-run `tournoi_rebound.json` journals are readable; the English
journal takes precedence and all new writes use it. Both files enter the card's
input fingerprint.

The optional catalogue uses the columns `question relevance id year title method
capability input_output result verification scale code`, followed by `score
data_availability transferability other_uses form_score verifiability effort`.
Effort is `low`, `medium` or `high`. Batch answers use `form` for the form word;
`form_score` is computed by the tool. The optional directions index uses
`direction year list subject source`. Existing `material.json` direction matches
with French field names are read and rewritten using the English names.
