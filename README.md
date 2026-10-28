# VanishingPoint (VP) - a deep-research skill with discipline plugins

VanishingPoint takes a question (or a project), searches the literature and the code through a date-bounded gateway,
triangulates, stops on saturation, writes a report in argued prose with a numbered bibliography, derives a machine annex
from it, then verifies the claims that carry a decision in a separate, fresh-context call. Then it stops. It writes no
code and tracks no project. Disciplines are text plugins (`plugins/<discipline>.md`): cs-ai, code, finance, biology, law,
plus a template to add one.

**This repository is the product and the source of truth.** It is what a user installs; nothing else is needed.
The benches that measured it are not part of this repository and are not required to use the skill.

Status: v0.2.0, measured on small benches (3 to 50 cases); see CHANGELOG.md.

## Installation

Requirements: Python >= 3.11 (standard library only at run time, no `pip install`; `pytest` only for one test file), `git` (code plugin), and one agent host:
Claude Code CLI or Codex CLI. Network access for the gateway (arXiv, OpenAlex, Crossref, Europe PMC, PubMed, Sourcegraph,
deps.dev, Hugging Face Papers, Software Heritage); every API key is optional (KEYS.md).

### Claude Code

Copy this directory to the user skills directory, or to a project's skills directory:

```
cp -r VanishingPoint-DeepResearch-Skill ~/.claude/skills/vanishingpoint        # user-wide
cp -r VanishingPoint-DeepResearch-Skill <project>/.claude/skills/vanishingpoint # one project
```

Claude Code loads `SKILL.md` through its YAML header (`name: vanishingpoint`) and triggers it on the phrases of the
`description` line, or when you type `/vanishingpoint`. Sub-agents (searchers, annex, verifier) use the Agent tool with
the search model (`sonnet` by default; `VP_SEARCH_MODEL` or `tools/config.json` `search_model`).

Interactive session: open `claude` in the working directory and ask the question (the skill triggers on its description, or type `/vanishingpoint`). Non-interactive runs (`claude -p`): background sub-agents are killed after an idle delay, so searchers die and `result.json` is never written; launch for instance:

```
CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0 claude -p --model claude-opus-5-5 --max-budget-usd 8 \
  --permission-mode dontAsk --allowedTools "Bash(python3 -I $SKILL/tools/*)" Read Write Agent Glob Grep Skill \
  "Use the vanishingpoint skill. T = 2026-10-27. <your question>. Work in the current directory."
```

### Codex CLI

Codex CLI (checked with codex-cli 0.160.1) discovers skills in `~/.codex/skills/<name>/SKILL.md` (user-wide) and in
`<project>/.agents/skills/<name>/SKILL.md` (one project); the YAML header (`name`, `description`) is read as for Claude Code:

```
cp -r VanishingPoint-DeepResearch-Skill ~/.codex/skills/vanishingpoint          # user-wide
cp -r VanishingPoint-DeepResearch-Skill <project>/.agents/skills/vanishingpoint  # one project
```

Codex has no sub-agents: the agent runs the 3 to 5 searches itself, in sequence, writing the same `searches/<n>.md` files,
and does the annex and the verification as separate steps (or as `codex exec` sub-processes when the host allows it).
Export `VP_HOST=openai` in the shell that launches Codex (`export VP_HOST=openai`, or put it in a profile) so that the tools that call a model (`tools/verifier.py`, `tools/whole_reading.py`) use the
`codex exec` profile of `tools/config.json` instead of `claude -p`. The gateway needs network access: Codex's sandbox blocks the network by default, interactive or not; launch with
`codex -c sandbox_workspace_write.network_access=true` (interactive) or `codex exec -s workspace-write -c sandbox_workspace_write.network_access=true`
(or set it in `~/.codex/config.toml`), otherwise every gateway call fails with a transport error. The Codex sandbox (bubblewrap) needs unprivileged user namespaces: in a
container that forbids them, every shell command fails with "bwrap: No permissions to create a new namespace" before Python
starts; fix the host (enable user namespaces), do not bypass the sandbox. Tell the agent to read SKILL.md with its file reader: `tools/` holds
only the scripts listed below, there is no file-reading script. If your Codex version does not list the skill (ask it "which skills are
available?"), add to the project's `AGENTS.md` the block below, which points to the file:

```
## VanishingPoint
For deep research questions ("state of the art", "what does this paper say", "does this repository have anything we
could take"), read and apply `<path to the skill>/SKILL.md` in full (for instance `~/.codex/skills/vanishingpoint/SKILL.md`
or `.agents/skills/vanishingpoint/SKILL.md`), then the plugin it selects.
```

## First run

1. Create a working directory for the question (one directory per question) and open the agent there.
2. Optional, once: `python3 -I "$SKILL/tools/check_keys.py"` (with `SKILL=~/.claude/skills/vanishingpoint` or `~/.codex/skills/vanishingpoint`: the tools live in the skill directory, not in the working directory) prints, per plugin, the sources that are active, degraded or skipped
   for lack of a key, with the link to obtain each key (never a value). KEYS.md explains where keys go (`~/.config/vp/`).
3. Ask the question, with the date T if it is not today, for instance:
   "Use the vanishingpoint skill. T = 2026-10-27. What does arXiv:2610.17471 say and what would it be useful for to a
   tool that splits plans into tasks? Work in the current directory."
4. The skill writes, in the working directory: `scope.md` (framing, angles, waves), `searches/<n>.md` (one per searcher,
   with receipts), `REPORT.md` (the report), `card.json` and `result.json` (machine annex), `verdicts.json` and
   `sources/<key>.txt` (verification), `run.json` (header derived from the gateway journal), `state/` (gateway journal,
   receipts without URL nor key). The code plugin adds `capsule.md` (input) and `mechanisms.json` (output).
5. Check before using the report: `python3 -I "$SKILL/tools/validate_card.py" <dir> --header` (12 numbered mechanical checks; empty output
   = valid). A report that keeps ABSENT or INVALID claims unhandled is not delivered as valid.

Manual gateway test (no agent, no key, needs network; run from anywhere, `SKILL` as above):

```
python3 -I "$SKILL/tools/gateway.py" --plugin "$SKILL/plugins/cs-ai.md" --T 2026-10-26 --run try --state /tmp/vp-state sources
python3 -I "$SKILL/tools/gateway.py" --plugin "$SKILL/plugins/cs-ai.md" --T 2026-10-26 --run try --state /tmp/vp-state search-crossref "retrieval augmented generation" --n 5
python3 -I "$SKILL/tools/gateway.py" --T 2026-10-26 --run try --state /tmp/vp-state read arxiv:1706.03762
```

## Keys (optional) and access policy

- KEYS.md: every key is optional; without one, the source is skipped or degraded with a receipt, never "nothing found".
  Resolution: environment variable `NAME`, else `~/.config/vp/<name in lower case>.key`. No value is ever printed or logged.
- ACCESS-POLICY.md: three levels (documented API; public pages even under robots.txt with a declared user agent, cadence
  and cache; never a reserved access, a captcha bypass or a service whose terms forbid automation). Set `VP_CONTACT` to a
  team or project address for the user agent, never a personal one.

## Modes

| Mode | How to switch it on | What it does | Cost |
|---|---|---|---|
| standard (default) | nothing | the whole method; verification of what carries a decision, one pass | about 2-3 USD per academic question; about 7 USD per code study with the whole reading |
| audit | `VP_MODE=audit`, or `~/.config/vp/mode` containing `audit`, or "audit mode" in the question | exhaustive card (every atomic claim), verification by batches at fresh context, corrections re-verified once | 6 to 7 times the standard mode (measured: -6.7 points of false claims) |
| contradictor (code plugin) | `VP_CONTRADICTORS` or `~/.config/vp/contradictors` = `codex` (Codex CLI, on a Claude Code host), `claude` (`claude -p`, on a Codex host), `kimi` or `gemini` (OpenRouter, `OPENROUTER_API_KEY`, optional) | after the report, a model of another family tries to prove it wrong; what survives a mechanical check and a fresh-context reread is annotated or added by the orchestrator; the tool never edits the report | 0 USD for Codex on a subscription, about 0.26 USD per call through OpenRouter, + about 0.6 USD of rereads per report (measured on 6 code cases: Codex, Kimi and Gemini passed the criterion; `claude` as contradictor not measured) |

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
See `examples/capsule-template.md` (and its `.json` twin) for the shape of a context capsule.

## Costs measured

- Standard mode, academic question (cs-ai, biology, finance): about 2 to 3 USD with an Opus orchestrator and Sonnet
  searchers (Claude Code); about 2x the cost of the reference deep-research method for the same result.
- Standard mode, code study with the whole reading before verdicts: about 7 USD (the whole reading alone: 0.9 to 2.6 USD,
  65-290 k input tokens, counted apart in `state/whole-reading/receipt.json`).
- Audit mode: 6 to 7 times the standard mode.
- Contradictor option (code plugin): 0 USD for Codex on a subscription (the natural contradictor on a Claude Code host), about
  0.26 USD per call through OpenRouter (Kimi or Gemini), plus about 0.6 USD of fresh-context rereads per report
  (`contradictor.json` carries the figures).
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
5. Sources without an API (level 2 pages, browser-driven pages) are declared in the plugins but not wired in the gateway;
   many "not wired" engines are listed as such in the `sources` output.

The figures above come from small benches (3 to 50 cases each) run by the authors; the benches, protocols and raw
traces are not part of this repository.

## Adding a plugin

One file `plugins/<discipline>.md`, four fixed sections in this order and under these exact titles: `## Sources`, `## Discipline
biases`, `## Output format`, `## Verification rules` (copy `plugins/_TEMPLATE.md`); the engine reads it as is, there is no registry.
The gateway reads, in the Sources section, a fenced block:

````
```sources
engines: openalex, crossref, arxiv     # wired engines: pubmed, europepmc, crossref, openalex, arxiv ; code, versions, paper-code, provenance
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

## Tests

```
for t in tests/test_*.py; do python3 -I "$t"; done        # unittest, offline (test_code_capsule.py needs pytest: python3 -m pytest -q tests/test_code_capsule.py)
python3 -I tests/test_gateway.py --online                 # optional, network: forbidden reviews must stay unfindable
```

Run the tests as a normal user (not root): the code-capsule and whole-reading tests create throwaway git repositories.

## Layout

```
SKILL.md            the engine (one file, read by the host)        plugins/     cs-ai, code, finance, biology, law, _TEMPLATE
tools/gateway.py    date-bounded documentary access                tools/verifier.py (+ verifier/ROLE.md, citation_check.py, fetch_fulltext.py)
tools/check_keys.py keys and mode                                   tools/validate_card.py, validate_result.py   mechanical checks
tools/code_capsule.py, condense_repo.py, whole_reading.py, contradictor.py   code plugin tools (capsule, Y condensation, whole reading, contradictor)
tools/config.json   caps, models, host command profiles             tests/  examples/  KEYS.md  ACCESS-POLICY.md  CHANGELOG.md  LICENSE  NOTICE
```

## Attribution

The method is a rewrite, in the authors' own words, inspired by existing deep-research skills (the one published by
199 Biotechnologies among others); none of their text, prompts or templates is copied. The tools are original code
(Python standard library only); no third-party code is copied (the repository-condensation idea owes something to
Aider's repository map, as an idea only).

## License

Apache License 2.0; see LICENSE and NOTICE. The reports the skill produces are research aids, not legal, financial or
medical advice; every claim they contain must be read with its verification status.
