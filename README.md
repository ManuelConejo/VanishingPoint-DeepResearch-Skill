# VanishingPoint (VP) - a deep-research skill with discipline plugins

VanishingPoint takes a question (or a project), searches the literature and the code through a date-bounded gateway,
triangulates, stops on saturation, writes a report in argued prose with a numbered bibliography, derives a machine annex
from it, then verifies the claims that carry a decision in a separate, fresh-context call. Then it stops. It writes no
code and tracks no project. Disciplines are text plugins (`plugins/<discipline>.md`): cs-ai, code, finance, biology, law,
plus a template to add one.

**This repository is the product and the source of truth.** It is what a user installs; nothing else is needed.
The benches that measured it are not part of this repository and are not required to use the skill.

Status: v0.6.5, research preview. Measured on small private benches (3 to 50 cases); no public benchmark yet; see
"What is measured, what is not" below and CHANGELOG.md.

## In two minutes

- **You give**: a question and, optionally, a date T ("what was known before T").
- **It does**: 3 to 5 searches through a gateway that only returns documents dated before T (arXiv, OpenAlex, Crossref,
  PubMed, Europe PMC, OpenReview, code hosts... no key required), stops on saturation, writes the report, then a separate
  fresh-context call re-reads the sources and checks the claims that carry a decision.
- **You get**, in one directory: `REPORT.md` / `REPORT.html` (eight sections, numbered bibliography, each checked claim
  shown with the exact source passage), `card.json` / `result.json` / `verdicts.json` (machine annex and verdicts:
  FOUND, DISTORTED, ABSENT, INVALID, SOURCE-UNAVAILABLE, UNVERIFIED), `studies.csv` and `references.bib` / `.ris`.
- **It costs**: about 3 USD of model usage per academic question on Claude Code (2.8 to 3.0 USD measured, verification
  included), up to about 10 USD on long legal texts, more with the optional full-text verification (see the example);
  0 USD metered on a Codex subscription.
- **See a real run**: [`examples/report-cs-ai/`](examples/report-cs-ai/) (question, report, verdicts, cited passages,
  with its limits).
- **Use it**: [USAGE.md](USAGE.md) (how to ask, reading the result, plugins, optional modes, keys, costs, troubleshooting).

## Installation

Requirements: Python >= 3.11 (standard library only, no `pip install`; `pytest` is optional), `git` (code plugin), and one agent host:
Claude Code CLI or Codex CLI. Network access for the gateway (arXiv, OpenAlex, Crossref, Europe PMC, PubMed, Sourcegraph,
deps.dev, Hugging Face Papers, Software Heritage); every API key is optional (KEYS.md).

### Claude Code

Clone the repository straight into the skills directory (git creates the missing parent directories), user-wide or
for one project:

```
git clone https://github.com/ManuelConejo/VanishingPoint-DeepResearch-Skill.git ~/.claude/skills/vanishingpoint            # user-wide
git clone https://github.com/ManuelConejo/VanishingPoint-DeepResearch-Skill.git <project>/.claude/skills/vanishingpoint    # one project
```

Update: `git -C ~/.claude/skills/vanishingpoint pull` (or `git -C <project>/.claude/skills/vanishingpoint pull`).

### First run

```
python3 -I ~/.claude/skills/vanishingpoint/tools/check_keys.py --plugin cs-ai     # offline: which sources are active, which keys are missing
python3 -I ~/.claude/skills/vanishingpoint/tools/setup_keys.py contact            # recommended: your contact e-mail (Unpaywall, SEC EDGAR, polite Crossref)
```

Then open `claude` in an empty directory and ask, for instance: "Use the vanishingpoint skill. T = 2026-10-27. What is the
state of the art on speculative decoding for LLM inference? Work in the current directory." (Codex: same lines with
`~/.codex/skills/vanishingpoint`; every key, and the contact, stays optional.)

Claude Code loads `SKILL.md` through its YAML header (`name: vanishingpoint`) and triggers it on the phrases of the
`description` line, or when you type `/vanishingpoint`. Sub-agents (searchers, annex, verifier) use the Agent tool with
the search model (`sonnet` by default; `VP_SEARCH_MODEL` or `tools/config.json` `search_model`).

Interactive session: open `claude` in the working directory and ask the question (the skill triggers on its description, or type `/vanishingpoint`). Non-interactive runs (`claude -p`): background sub-agents are killed after an idle delay, so searchers die and `result.json` is never written; launch for instance:

```
CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0 claude -p --model opus --max-budget-usd 8 \
  --permission-mode dontAsk --allowedTools "Bash(python3 -I $SKILL/tools/*)" Read Write Agent Glob Grep Skill \
  "Use the vanishingpoint skill. T = 2026-10-27. <your question>. Work in the current directory."
```

### Install as a Claude Code plugin

The repository is also a Claude Code plugin marketplace (`.claude-plugin/marketplace.json` and `.claude-plugin/plugin.json`
at the root; the plugin is the repository itself, loaded as a single skill). In a Claude Code session:

```
/plugin marketplace add ManuelConejo/VanishingPoint-DeepResearch-Skill
/plugin install vanishingpoint@vanishingpoint-deepresearch
```

The skill is then `/vanishingpoint:vanishingpoint` and triggers on its description as before. Update:
`claude plugin marketplace update vanishingpoint-deepresearch`, then `claude plugin update vanishingpoint@vanishingpoint-deepresearch`
(the plugin follows the `version` of `plugin.json`). The plugin copy lives in Claude Code's plugin directory, not in
`~/.claude/skills/`: for the First run commands, use the path that `claude plugin list` prints, or ask Claude to run
`tools/check_keys.py` and `tools/setup_keys.py contact` from the skill directory. Install it either as a plugin or as a
cloned skill, not both (two copies of the same skill would compete). The clone above stays the simplest way.

### Codex CLI

Codex CLI (checked with codex-cli 0.160.1) discovers skills in `~/.codex/skills/<name>/SKILL.md` (user-wide) and in
`<project>/.agents/skills/<name>/SKILL.md` (one project); the YAML header (`name`, `description`) is read as for Claude Code:

```
git clone https://github.com/ManuelConejo/VanishingPoint-DeepResearch-Skill.git ~/.codex/skills/vanishingpoint             # user-wide
git clone https://github.com/ManuelConejo/VanishingPoint-DeepResearch-Skill.git <project>/.agents/skills/vanishingpoint    # one project
```

Update: `git -C ~/.codex/skills/vanishingpoint pull`.

Codex has no sub-agents: the agent runs the 3 to 5 searches itself, in sequence, writing the same `searches/<n>.md` files,
and does the annex and the verification as separate steps (or as `codex exec` sub-processes when the host allows it).
Export `VP_HOST=openai` in the shell that launches Codex (`export VP_HOST=openai`, or put it in a profile) so that the tools that call a model (`tools/verifier.py`, `tools/whole_reading.py`) use the
`codex exec` profile of `tools/config.json` instead of `claude -p`. The gateway needs network access: Codex's sandbox blocks the network by default, interactive or not; launch with
`codex -c sandbox_workspace_write.network_access=true` (interactive) or `codex exec -s workspace-write -c sandbox_workspace_write.network_access=true`
(or set it in `~/.codex/config.toml`), otherwise every gateway call fails with a transport error. The Codex sandbox (bubblewrap) needs unprivileged user namespaces: in a
container that forbids them, every shell command fails with "bwrap: No permissions to create a new namespace" before Python
starts; fix the host (enable user namespaces), do not bypass the sandbox. The verifier detects this case (`tools/verifier.py` under
`VP_HOST=openai`): instead of returning every claim as UNVERIFIED silently, it stops after the first failed call, writes
`host_problem` in `verdicts.json` and in `state/verifier.json`, prints the reason on stderr and exits with code 3. Fallback, in this
order: enable unprivileged user namespaces on the host; or run the verification step with the Claude Code profile when the `claude`
CLI is installed (`--host claude`, or `VP_HOST=claude` for that command only); or verify without script as SKILL.md section 7
describes (sources re-read with the gateway's `read`), the claims left unverified being flagged in the methodology appendix. Tell the agent to read SKILL.md with its file reader: `tools/` holds
only the scripts listed below, there is no file-reading script. If your Codex version does not list the skill (ask it "which skills are
available?"), add to the project's `AGENTS.md` the block below, which points to the file:

```
## VanishingPoint
For deep research questions ("state of the art", "what does this paper say", "does this repository have anything we
could take"), read and apply `<path to the skill>/SKILL.md` in full (for instance `~/.codex/skills/vanishingpoint/SKILL.md`
or `.agents/skills/vanishingpoint/SKILL.md`), then the plugin it selects.
```

## Step by step

Set once, in the shell you use: `export SKILL=~/.claude/skills/vanishingpoint` (or `~/.codex/skills/vanishingpoint`);
every command below uses it.

1. Create a working directory for the question (one directory per question) and open the agent there.
2. Optional, once: `python3 -I "$SKILL/tools/check_keys.py"` (with `SKILL=~/.claude/skills/vanishingpoint` or `~/.codex/skills/vanishingpoint`: the tools live in the skill directory, not in the working directory) prints, per plugin, the sources that are active, degraded or skipped
   for lack of a key, with the link to obtain each key (never a value). To install one: `python3 -I "$SKILL/tools/setup_keys.py" <NAME>`
   (for instance `contact`, `piste` or `openalex`; without a name it lists the keys and asks): hidden input, saved, then checked live,
   one plain verdict line per source. Manual method (secondary): KEYS.md, files in `~/.config/vp/`.
3. Ask the question, with the date T if it is not today, for instance:
   "Use the vanishingpoint skill. T = 2026-10-27. What does arXiv:2610.17471 say and what would it be useful for to a
   tool that splits plans into tasks? Work in the current directory."
4. The skill writes, in the working directory: `scope.md` (framing, angles, waves), `searches/<n>.md` (one per searcher,
   with receipts), `REPORT.md` (the report), `card.json` and `result.json` (machine annex), `verdicts.json` and
   `sources/<key>/source.txt` (verification), `run.json` (header derived from the gateway journal), `state/` (gateway journal,
   receipts without URL nor key). The code plugin adds `capsule.md` (input) and `mechanisms.json` (output).
5. Check before using the report: `python3 -I "$SKILL/tools/validate_card.py" <dir> --header` (14 numbered mechanical checks, the 13th: end steps run by `finish_run.py` below, the 14th: no cross-source statement on a single `[n]`; `OK`
   = valid; without `state/journal.jsonl` the header is left as it is). A report that keeps ABSENT or INVALID claims unhandled is not delivered as valid.
6. Export: `python3 -I "$SKILL/tools/export_report.py" <dir> [--pdf] [--open]` writes `REPORT.html` (one self-contained page, prints to PDF from any browser) and, with `--pdf`, `REPORT.pdf` through WeasyPrint, Chromium, wkhtmltopdf or pandoc when one is installed (nothing is installed, no network). Then `python3 -I "$SKILL/tools/export_data.py" <dir>` writes `studies.csv` (one row per study, criteria and verification counts) and `references.bib` / `.ris` / `.json` (CSL-JSON) for reference managers.

All end steps in one command (SKILL.md section 8; `validate_card.py` run alone refuses a run whose end steps did not run on the current files, check 13, receipt `state/finish_run.json`): `python3 -I "$SKILL/tools/finish_run.py" <dir> [--T YYYY-MM-DD] [--plugin plugins/law.md] [--offline] [--rw-csv FILE] [--json] [--prisma] [--followups] [--prior-art]` runs `validate_card.py --header`, `validate_result.py`, the mechanical retraction check of the plugins (Crossref `updated-by` / `update-to`, Retraction Watch entries; `retractions.json`, `unknown` never turned into clean), `law_checks.py` for a law run, `export_report.py --pdf --open` and `export_data.py`; each step reports ok / problems / skipped and never stops the others; exit 0 only when validation passed; the produced paths are printed.

In the conversation (v0.6.0; both steps below are prepared by a tool, no model call):

- **Follow-up.** "Dig into point 3", "and for France?" after a delivered run: a short complementary run in `<dir>/followups/<n>/`
  (`tools/followup.py`: same T and plugins, the parent's gateway cache and the sources already read reused, 1 to 3 angles the parent
  did not cover), verified like any run; `finish_run.py` on it delivers `<dir>/FOLLOWUP-<n>.md` / `.html` / `.pdf`; the main report is
  never modified. Measured once (v0.6.0 trials): all criteria met, about 1.5 USD with a Sonnet orchestrator, verification included.
- **Resume.** "Resume the research in <dir>": `tools/resume.py` names the step to resume (frame, search, complete, write, annex, verify,
  apply, deliver) from the files present and what is missing; the run continues with the same T, plugins and gateway counter, nothing
  already written is redone. Measured once (v0.6.0 trials): all criteria met, at the cost of the reference run.

Command-line tools, not used by the skill by default (shipped in v0.6.0, kept on a waiting list after the ergonomics trials, see
CHANGELOG): `tools/summary.py` (`SUMMARY.md`, an end-of-run message; also `finish_run.py --summary`, off by default),
`tools/progress.py` (a one-line progress status), `tools/parse_date.py` (a date in words -> T), `tools/new_run.py` (creates a new
working directory), `tools/cost.py` (an estimate before an expensive option, a plan under a budget), `tools/report_lang.py` (the
eight section titles in English, French, Spanish, German; since v0.6.3 the skill uses it to write the report in the language of
the question). Each prints its usage with `--help`.

Update of a previous run (living review): ask "update my review of <dir>"; the skill reruns the question at today's T in a new directory, then `python3 -I "$SKILL/tools/living_diff.py" <old dir> <new dir>` writes `UPDATE.md` and `update.json` (what changed since the old T); neither report is edited by the tool.

Manual gateway test (no agent, no key, needs network; run from anywhere, `SKILL` as above):

```
python3 -I "$SKILL/tools/gateway.py" --plugin "$SKILL/plugins/cs-ai.md" --T 2026-10-26 --run try --state /tmp/vp-state sources
python3 -I "$SKILL/tools/gateway.py" --plugin "$SKILL/plugins/cs-ai.md" --T 2026-10-26 --run try --state /tmp/vp-state search-crossref "retrieval augmented generation" --n 5
python3 -I "$SKILL/tools/gateway.py" --T 2026-10-26 --run try --state /tmp/vp-state read arxiv:1706.03762
```

## Keys (optional) and access policy

- KEYS.md: every key is optional; without one, the source is skipped or degraded with a receipt, never "nothing found".
  Install and check one: `python3 -I "$SKILL/tools/setup_keys.py" <NAME>` (`--check`, `--remove`). Manual method: environment variable
  `NAME`, else the file `~/.config/vp/<name in lowercase>.key` (the resolution order). No value is ever printed or logged.
- ACCESS-POLICY.md: three levels (documented API; public pages even under robots.txt with a declared user agent, cadence
  and cache; never a reserved access, a captcha bypass or a service whose terms forbid automation). Set `VP_CONTACT` to a
  team or project address for the user agent, never a personal one: `python3 -I tools/setup_keys.py contact` writes it to
  `~/.config/vp/vp_contact.key` (0600) after checking its form; it unlocks Unpaywall and SEC EDGAR and identifies the skill
  politely to Crossref and public pages. The address is sent to the providers in the identification header.

## Modes

| Mode | How to switch it on | What it does | Cost |
|---|---|---|---|
| standard (default) | nothing | the whole method; verification of what carries a decision, one pass | about 2-3 USD per academic question; about 7 USD per code study with the whole reading |
| audit | `VP_MODE=audit`, or `~/.config/vp/mode` containing `audit`, or "audit mode" in the question | exhaustive card (every atomic claim), verification by batches at fresh context, corrections re-verified once | 6 to 7 times the standard mode (measured: -6.7 points of false claims) |
| contradictor (code plugin) | `VP_CONTRADICTORS` or `~/.config/vp/contradictors` = one or more of `openai[:<model>]` (Codex CLI), `claude[:<model>]` (`claude -p`), `<provider>:<model>` (any OpenAI-compatible API of `tools/config.json`: `openrouter`, `gemini`, `openai-api`, `mistral`, `ollama`, or yours); no model name is fixed in the skill | after the report, a model of another family tries to prove it wrong; what survives a mechanical check and a fresh-context reread is annotated or added by the orchestrator; the tool never edits the report | 0 USD for the Codex CLI on a subscription, about 0.26 USD per call through an API, + about 0.6 USD of rereads per report (measured on 6 code cases with three models of 2026-10-27; other models, providers and `claude` as contradictor not measured) |
| prior art | ask "prior art?", "has this already been done?" | the idea is cut into essential elements; `PRIOR-ART.md` answers Exists / Partially / Not found, decided by code from the verified claims (no `REPORT.md`) | same engine and verifier; answer rule not measured |
| PRISMA / follow-ups | ask for a PRISMA flow diagram or follow-up questions | `PRISMA.md` / `.svg` and `FOLLOWUPS.md`, derived by code from the run (`finish_run.py --prisma --followups`), appended to `REPORT.html` | no model or gateway call |

`tools/check_keys.py` prints the active mode at the start of a run; the report's Methodology Appendix states it. The law
plugin recommends audit mode for binding conclusions; it never switches it on by itself.

## What the skill delivers

`REPORT.md` has exactly eight sections: Executive Summary (200-400 words), Introduction, Main Analysis (4 to 8 findings,
each argued in four steps: what the sources establish, what contradicts it, consequence, verdict), Synthesis & Insights,
Limitations & Caveats, Recommendations, Bibliography (numbered `[n]`, one line per document with its identifier and the
basis read), Methodology Appendix (process, "Source coverage" block, verification statuses, cost, mode). The annex gives
`card.json` (the claims checked, one per `criteria` field, per figure of the summary and per verdict) and `result.json`
(the studies with six criteria fields, saturation, calls used, verification rule). The code plugin adds `mechanisms.json`
(ten fields per mechanism: Y side `file:line@SHA`, target seam in X, GO / WATCH / NO-GO, what not to take, licence).
See `examples/report-cs-ai/` for a real, unedited run and `examples/capsule-template.md` (and its `.json` twin) for
the shape of a context capsule.

## Costs measured

- Standard mode, academic question (cs-ai, biology, finance): about 2 to 3 USD with an Opus orchestrator and Sonnet
  searchers (Claude Code); about 2x the cost of the reference deep-research method for the same result.
- Standard mode, code study with the whole reading before verdicts: about 7 USD (the whole reading alone: 0.9 to 2.6 USD,
  65-290 k input tokens, counted apart in `state/whole-reading/receipt.json`).
- Audit mode: 6 to 7 times the standard mode.
- Contradictor option (code plugin): 0 USD for the Codex CLI on a subscription (the natural contradictor on a Claude Code host),
  about 0.26 USD per call through an API (OpenRouter, 2026-10-27), plus about 0.6 USD of fresh-context rereads per report
  (`contradictor.json` carries the figures, and says when a provider does not report its cost).
- Codex CLI on a subscription: 0 USD per run on the metered side; the same number of gateway calls.

## Limits, measured honestly

1. The skill does not find more than the reference deep-research method it rewrites: equal recall, equal F1 within noise
   (10 questions, same grader); the owner preferred the reference reports 5/5 blind for readability.
2. Its value is elsewhere: the whole reading before verdicts (exclusive verified findings in 5 of 6 code cases), the
   downstream verification (-4.2 points of false claims at equal recall on 50 questions) and the discipline plugins
   (sources, biases, verification rules); the two reports were judged equally safe for a downstream reader (0 false
   reference propagated).
3. It costs about 2x the reference method in standard mode; the form (eight sections rewritten after verification) is
   most of that cost.
4. On code, no variant beat a plain model on the "what would Y bring to X" task on our benches; the code plugin is kept for
   its capsule, its seams and the whole reading, not as a better finder.
5. Sources without an API (level 2 pages) are declared in the plugins but not wired in the gateway;
   many "not wired" engines are listed as such in the `sources` output.

The figures above come from small benches (3 to 50 cases each) run by the authors; the benches, protocols and raw
traces are not part of this repository.

## What is measured, what is not

Measured (private benches, small n, judged by models of other families and by the author):
- downstream verification: -4.2 points of false claims at equal recall (50 questions);
- recall equal to the reference deep-research method it rewrites (10 questions); about 2x its cost;
- whole reading before verdicts on code: exclusive verified findings in 5 of 6 code cases;
- contradictor option: 6 code cases, three models of 2026-10-27;
- every tool: an offline test suite (`tests/`, about 320 tests, standard library only, about one minute).

Not measured or not verified:
- no public benchmark: the figures above cannot be reproduced from this repository yet;
- PISTE engines (Judilibre, Legifrance) are coded and tested offline, **not yet verified on the live service**;
- the verifier's claim windows are tested offline; their catch rate and cost with a model are not measured;
- `claude` as contradictor, and other models or providers than those listed;
- engines listed "not wired" by `sources` are declared only.

## Adding a plugin

One file `plugins/<discipline>.md`, four fixed sections in this order and under these exact titles: `## Sources`, `## Discipline
biases`, `## Output format`, `## Verification rules` (copy `plugins/_TEMPLATE.md`); the engine reads it as is, there is no registry.
The gateway reads, in the Sources section, a fenced block:

````
```sources
engines: openalex, crossref, arxiv     # wired engines: pubmed, europepmc, crossref, openalex, arxiv, clinicaltrials, biorxiv, medrxiv, dblp, econbiz, dbnomics, fred (FRED_API_KEY), edgar (VP_CONTACT e-mail), opencitations, unpaywall (VP_CONTACT e-mail), datacite ; law: eurlex, justice-administrative, hal, theses-fr, hudoc, hudoc-feed, europarl, isidore, judilibre, legifrance (PISTE pair) ; ai: openreview, zenodo, hal-info, hf-models, hf-datasets, standards, proceedings ; code, versions, paper-code, provenance, osv, ecosyste.ms, github-advisory
since: 2015                            # optional lower bound (year)
cap: 60                                # optional safety cap on calls
keys: OPENALEX_KEY                     # optional keys, resolved as in KEYS.md, never required
useful_when: openalex=broad searches, citation chaining   # per free-key source: read by check_keys.py --suggest
access: openalex=api, crossref=api     # api | page | browser | tos_forbidden | technical_block (ACCESS-POLICY.md)
disabled: ssrn=tos_forbidden           # listed, never called, with the reason
```
````

An engine declared but not wired is listed `not_wired` by `sources` and refused with a receipt. Several plugins: union of
the engines, lowest cap, oldest lower bound. The rest of the section is text for the engine and the searchers.

## Adding a source

One source = one file `tools/sources/<name>.py` (copy `tools/sources/_TEMPLATE.py`): its `SOURCE` declaration (engine, identifier
prefix, hosts and pacing, access level, terms, date-barrier notes, optional key) and its `search` / `read` functions. Everything else
(gateway engines and routing, `check_keys.py`, `setup_keys.py`, validators, exports) is derived from the registry. Your own sources
can live in `~/.config/vp/sources/` (loaded with `VP_USER_SOURCES=1`). Rules, barrier, keys and tests: [CONTRIBUTING.md](CONTRIBUTING.md).

## Tests

```
for t in tests/test_*.py; do python3 -I "$t"; done        # unittest, offline (test_code_capsule.py also runs under pytest)
python3 -I tests/test_gateway.py --online                 # optional, network: forbidden reviews must stay unfindable
```

Run the tests as a normal user (not root): the code-capsule and whole-reading tests create throwaway git repositories.
Checked on Python 3.12 (Ubuntu 24.04, `env -i`, empty home): all files pass, about one minute. The system Python often has
no `pytest`; without it, skip `test_code_capsule.py` or install it (`python3 -m pip install --user pytest`).

## Layout

```
SKILL.md            the engine (one file, read by the host)        plugins/     cs-ai, code, finance, biology, law, _TEMPLATE
tools/gateway.py    date-bounded documentary access (sources: tools/sources/, one file each)   tools/verifier.py (+ verifier/ROLE.md, citation_check.py, fetch_fulltext.py, windows.py)
tools/check_keys.py keys and mode (setup_keys.py: install + live check) tools/validate_card.py, validate_result.py   mechanical checks
tools/finish_run.py all end steps in one command (checks, retractions, law checks, exports; SKILL.md section 8; --summary optional)
tools/followup.py, resume.py   follow-up in the conversation, resuming an interrupted run (v0.6.0)
tools/export_report.py, export_data.py, passages.py, living_diff.py, law_checks.py   exports, cited passages, living review, legal rules
tools/code_capsule.py, code_sources.py (library), condense_repo.py, whole_reading.py, contradictor.py   code plugin tools (capsule, Y condensation, whole reading, contradictor)
tools/prior_art.py, prisma.py, followups.py   optional sections of SKILL.md (prior art, PRISMA flow diagram, follow-up questions)
tools/evidence_bank.py, contradictions.py, summary.py, progress.py, parse_date.py, new_run.py, cost.py   command-line tools, not used by the skill by default; report_lang.py: report language
tools/config.json   caps, models, host command profiles             tests/  examples/  KEYS.md  ACCESS-POLICY.md  CONTRIBUTING.md  CHANGELOG.md  USAGE.md  LICENSE  NOTICE
.claude-plugin/     plugin.json + marketplace.json: the repository as a Claude Code plugin (the skill directory needs neither)
```

## Attribution

The method is a rewrite, in the authors' own words, inspired by existing deep-research skills; none of their text,
prompts or templates is copied. The tools are original code
(Python standard library only); no third-party code is copied (the repository-condensation idea owes something to
Aider's repository map, as an idea only).

## License

Apache License 2.0; see LICENSE and NOTICE. The reports the skill produces are research aids, not legal, financial or
medical advice; every claim they contain must be read with its verification status.
