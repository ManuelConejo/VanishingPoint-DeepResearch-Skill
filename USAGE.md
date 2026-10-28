# Using VanishingPoint

A practical guide for someone who has installed the skill and wants to use it in Claude Code or Codex CLI. Installation,
requirements and the method itself are in [README.md](README.md); the engine's full rules are in [SKILL.md](SKILL.md).
Everything below applies to v0.5.4.

In the commands, `$SKILL` is the skill directory, set once in your shell:

```
export SKILL=~/.claude/skills/vanishingpoint      # or ~/.codex/skills/vanishingpoint
```

Installed with `git clone` (README.md, "Installation"), the skill updates with `git -C "$SKILL" pull`. Installed as a Claude
Code plugin, `$SKILL` is the directory that `claude plugin list` prints for `vanishingpoint`.

## 1. First research in 5 minutes

1. Create an empty directory for the question (one directory per question) and open your agent there
   (`claude`, or `codex` with network access, see section 8).
2. Ask the question. The skill triggers on its description or on `/vanishingpoint` (Claude Code). Phrasings that trigger it:

   | You want | Say, for instance |
   |---|---|
   | a state of the art | "Deep research: what is the state of the art on speculative decoding for LLM inference?" |
   | what is known | "What is known about the effect of intermittent fasting on HbA1c in type 2 diabetes?" |
   | one paper explained | "What does arXiv:1706.03762 say, and what would it be useful for in a translation pipeline?" |
   | a comparison | "Compare LoRA and full fine-tuning from the literature: cost and quality." |
   | a list of studies | "Find the studies that measured retrieval-augmented generation on legal question answering." |
   | code from another project | "Does this repository have anything we could take? Y = <repo>@<SHA>, X = our repo." |

   The most reliable form names the skill, the date and the directory, as in the README:
   "Use the vanishingpoint skill. T = 2026-10-27. <your question>. Work in the current directory."
   The skill is not meant for a question that one or two searches answer, nor for writing code.
3. **Date T.** T means "what was known before T". The gateway serves only documents dated before T; without T, T is today
   (nothing later than yesterday is served). Set a past T to see the evidence as it stood at a decision, a filing or a
   publication date, to avoid hindsight, or to rerun a question later on the same ground. The report states T in its Introduction.
4. **Where the results are**: in the working directory. Open `REPORT.html` first (one self-contained page, printable to
   PDF). The agent's final message lists the paths of the files it wrote and ends with a one-line summary.

| File | Content |
|---|---|
| `REPORT.md`, `REPORT.html` (`REPORT.pdf` if a converter is installed) | the report (section 2 of this guide) |
| `verdicts.json`, `PASSAGES.md`, `passages.json` | verification status of each checked claim, with the exact source passage |
| `card.json`, `result.json` | machine annex: claims checked; studies with six criteria fields |
| `studies.csv`, `references.bib`, `references.ris`, `references.json` | exports for spreadsheets and reference managers |
| `scope.md`, `searches/<n>.md` | framing and the searchers' notes, with gateway receipts |
| `run.json`, `state/`, `sources/` | calls per command (from the gateway journal), journal and cache, texts re-read by the verifier |
| `retractions.json` | mechanical retraction check of the DOIs (Crossref, Retraction Watch); `unknown` stays `unknown` |

The code plugin adds `capsule.md` (input) and `mechanisms.json`. A real, unedited run is in
[`examples/report-cs-ai/`](examples/report-cs-ai/).

## 2. Reading the result

**The eight sections of `REPORT.md`**, always in this order:

| Section | What to look for |
|---|---|
| Executive Summary | the answer in 200 to 400 words, with its `[n]`, and what remains open |
| Introduction | the question as framed, T, the plugins, the scope, and the assumptions made, each with what would change if it were wrong |
| Main Analysis | 4 to 8 findings; each states what the sources establish, what contradicts it, the consequence and a verdict (established / probable / open; GO / WATCH / NO-GO for code) |
| Synthesis & Insights | what the findings say together; the skill's own analysis, marked as such |
| Limitations & Caveats | counter-evidence, empty angles, inaccessible sources; says so if fewer than ten sources carry the report |
| Recommendations | what to do, watch or search next (never code) |
| Bibliography | numbered `[n]`, one line per document with its identifier and the basis read: `abstract` or `title` |
| Methodology Appendix | process, "Source coverage" block (active, degraded, skipped sources and why), verification counts, removals, cost, mode |

A `[n]` proves that a claim is **traceable** to a source; only the FOUND status proves that the source says it. A basis
`title` means only the title was read. Only what carries a decision is verified (the criteria of each study, the figures of
the Executive Summary, the verdict of each finding); the other sentences of the findings are traceable by their `[n]` but
not checked, and the Methodology Appendix says so.

**Verifier statuses** (in `verdicts.json`, counted in the Methodology Appendix):

| Status | Meaning | What the skill did | What you do |
|---|---|---|---|
| FOUND | the source supports every element of the claim | kept | usable; read the passage if the claim matters |
| DISTORTED | the source covers the point but one element differs | corrected from the discrepancy, **not re-verified** | recheck the corrected sentence against the passage before relying on it |
| ABSENT | nothing in the source supports the claim | removed from the report, listed in the appendix | nothing; a delivered report keeps none |
| INVALID | the cited fragments are not in the source text | removed, listed | nothing; same rule |
| SOURCE-UNAVAILABLE | the source could not be read, or only its abstract while the claim is about the body | kept, flagged as unverified | treat as unverified; read the source yourself |
| UNVERIFIED | the verifier did not reach it (call failed, budget) | kept, flagged as unverified | same |

`finish_run.py` refuses to validate a report that keeps an ABSENT or INVALID claim.

**Cited passages.** In `REPORT.html`, under each bibliography entry, every checked claim is shown with the exact source
sentence and the verified fragment highlighted (origin: full text, or record + abstract). A passage appears only when the
fragment is found in the text the verifier actually read (kept in `sources/`); `PASSAGES.md` and `passages.json` hold the same
content. If you copy a run without its `sources/` directory, regenerating the HTML shows no passages.

**Exports** (`tools/export_data.py`): `studies.csv` (one row per study: the six criteria, confidence, basis, and counts per
verification status), `references.bib` (BibTeX), `references.ris` (RIS), `references.json` (CSL-JSON), plus `passages.json`.

## 3. Choosing a discipline

The skill picks the plugin from the question; you can name it ("use the law plugin"). A question across disciplines uses
several plugins (union of their sources). The engines below are wired and keyless unless a key is named; each plugin also
lists engines it does not wire yet (`gateway.py ... sources` shows them as `not_wired`).

| Plugin | Wired sources | Example questions |
|---|---|---|
| `cs-ai` | OpenAlex, Crossref, arXiv, Europe PMC, dblp, OpenReview (reviews and decisions before T), Zenodo, HAL (computer science), HF Papers (paper to code), Hugging Face models and datasets, standards (RFC, PEP, W3C), open proceedings (ACL Anthology, PMLR, CVF) | "What is known about reward hacking in RLHF before 2026-01-01?"; "What does RFC 9000 change for connection migration?" |
| `code` | Sourcegraph code search (GitHub search with `VP_GITHUB_TOKEN`), package versions (PyPI, npm, crates.io + deps.dev), HF Papers, Software Heritage provenance, OSV advisories, ecosyste.ms usage, Hugging Face models and datasets; local repositories at a SHA | "Does <Y>@<SHA> have anything our project X could take?"; "What would Y bring to X?" |
| `finance` | EconBiz, OpenAlex, Crossref, Europe PMC, arXiv (econ, q-fin), DBnomics series (ECB, Eurostat, IMF, OECD, INSEE, BIS, World Bank...; current values marked `as_of: "now"`), FRED/ALFRED point-in-time series (`FRED_API_KEY`) | "What is the evidence on volatility targeting and drawdowns?"; "What did the literature say about negative rates and bank margins before 2020-01-01?" |
| `biology` | PubMed, Europe PMC, Crossref, OpenAlex, ClinicalTrials.gov (registered trials, published or not), bioRxiv and medRxiv preprints (dated per version) | "What is known about GLP-1 agonists and kidney outcomes?"; "Find the trials of X registered but never published." |
| `law` (France and Europe) | EUR-Lex (Cellar), ECHR case law (HUDOC), French administrative courts, HAL (law), theses.fr, European Parliament adopted texts, Isidore, OpenAlex; Judilibre and Legifrance with the PISTE pair | "What does the CJEU say about legitimate interest under the GDPR?"; "How do French administrative courts treat <issue>?" |

The code plugin needs a **context capsule** of your project, built by `tools/code_capsule.py` and reviewed by you (intention
and refusals are yours to write); see `plugins/code.md` "Context capsule" and `examples/capsule-template.md`. Without a
capsule, a code run stops before collection.

## 4. Optional modes, on request

All are off by default; none changes the standard deliverables unless stated.

| Mode | When to use it | How to ask | What it produces | Cost |
|---|---|---|---|---|
| Prior art | you want to know whether an idea, method or tool already existed at T | "Prior art? T = 2022-01-01. <idea>" ("has this already been done?", "does this already exist?") | `PRIOR-ART.md`: **Exists** / **Partially** / **Not found**, closest prior art with verified passages, what differs, what was searched; no `REPORT.md` | not measured; same engine and verifier as a standard run |
| PRISMA, follow-ups | a systematic-review flow diagram, or next questions to ask | "with a PRISMA flow diagram", "with follow-up questions" | `PRISMA.md`, `PRISMA.svg`, `prisma.json`; `FOLLOWUPS.md`, `followups.json` (3 to 5 questions); both appended to `REPORT.html` | no model call, no gateway call |
| Full-text verification | figures sit in the body of papers, not in abstracts | ask the assistant to run the verifier with `--fulltext`, or set `"fulltext": true` under `verifier` in `tools/config.json` | the verifier reads the open full text pinned before T of the sources carrying the most claims (at most `verifier.fulltext_cap`, 12) | multiplies the verifier cost: up to about 9 USD-equivalent for the verifier on a 12-paper report |
| Audit | figures or rules that commit (law, finance, clinical) | `VP_MODE=audit`, or `~/.config/vp/mode` containing `audit`, or "audit mode" in the question | every atomic claim checked, by batches; corrections re-verified once | 6 to 7 times the standard mode (measured: -6.7 points of false claims) |
| Contradictor (code plugin only) | a second model family should try to prove a code report wrong | `VP_CONTRADICTORS` or `~/.config/vp/contradictors` = `openai[:<model>]`, `claude[:<model>]` or `<provider>:<model>` | `contradictor.json`; findings annotated "contradicted by <family>" or added and verified | 0 USD with Codex CLI on a subscription; about 0.26 USD per API call + about 0.6 USD of rereads per report |
| Update a previous run | refresh a report at today's T | "update my review of <dir>" | a new run in a new directory, plus `UPDATE.md` and `update.json` (what changed) | a normal run |

Notes:
- **Prior art**: the answer is decided by code from the verified claims (Exists = one source dated before T discloses every
  element, each claim FOUND). DISTORTED, SOURCE-UNAVAILABLE and UNVERIFIED claims never count as disclosure. "Not found" is
  not a proof of absence; patents are not searched (no patent engine is wired).
- **PRISMA** boxes are counted from the run's own records; a box the run did not record is printed "not recorded".
- **Audit** is recommended by the law plugin for binding conclusions; it is never switched on by itself. `check_keys.py`
  prints the active mode (`Mode: standard` or `Mode: audit`).
- **Contradictor**: measured on 6 code cases with three models of 2026-10-27; `claude` as contradictor and other models are
  not measured. The tool refuses to run outside the code plugin.

**Command-line tools, not used automatically.** Two tools exist but the assistant does not run them (their SKILL.md sections
wait for a measure). Run them yourself on a finished run that still has its `sources/` directory:

```
python3 -I "$SKILL/tools/evidence_bank.py" <dir> --from-verdicts --html   # approximate bank from the verifier's fragments
python3 -I "$SKILL/tools/evidence_bank.py" <dir> --bank evidence.json     # check your own bank of verbatim quotes
python3 -I "$SKILL/tools/contradictions.py" <dir> --html                  # candidate contradictions between sources
```

- `evidence_bank.py` checks that every quote of `evidence.json` is an exact substring of a text the gateway served, then
  ties each report sentence carrying a `[n]` to quotes of its sources and prints the **supported share**. Outputs
  `EVIDENCE.md`, `evidence_check.json`, `EVIDENCE.html`. `--section "<title>"` lists the quotes one section may use.
- `contradictions.py` lists mechanical candidates between two sources (incompatible figures, opposite directions, contrary
  decisions), each with its two passages: `CONTRADICTIONS.md`, `contradictions.json`, `CONTRADICTIONS.html`. Nothing is
  filtered or removed; judgments you add in `contradictions-judged.json` are checked and shown.
- Neither makes a model or gateway call; neither is measured as a method.

## 5. Keys

Every key is optional. Without one, the source is skipped or degraded **with a receipt**, never reported as "nothing found",
and the report's "Source coverage" block says so.

```
python3 -I "$SKILL/tools/check_keys.py"                 # offline: per plugin, active / degraded / skipped sources, links
python3 -I "$SKILL/tools/check_keys.py" --plugin law    # one plugin
python3 -I "$SKILL/tools/setup_keys.py"                 # list every key, then ask which one to install
python3 -I "$SKILL/tools/setup_keys.py" contact         # recommended: your contact e-mail (form checked, then one Unpaywall request)
python3 -I "$SKILL/tools/setup_keys.py" openalex        # install one (hidden input), then a live check
python3 -I "$SKILL/tools/setup_keys.py" openalex --check
python3 -I "$SKILL/tools/setup_keys.py" openalex --remove
```

Keys are stored in `~/.config/vp/<name in lowercase>.key` (directory 0700, file 0600); an environment variable of the same
name takes precedence. No value is ever printed or logged.

| Short name | Variable | What it brings |
|---|---|---|
| `contact` | `VP_CONTACT` | an e-mail address, not a key: unlocks Unpaywall and SEC EDGAR (else 0 request) and identifies the skill politely to Crossref and public pages; sent to the providers in the User-Agent identification header |
| `openalex` | `OPENALEX_KEY` | OpenAlex daily budget x10; without it, a 429 is possible from the first call (Crossref fallback, reported) |
| `ncbi` | `NCBI_API_KEY` | PubMed at 10 requests/s instead of 3 |
| `github` | `VP_GITHUB_TOKEN` | GitHub code search (read-only token); without it only Sourcegraph searches code |
| `swh` | `SWH_TOKEN` | Software Heritage at 3 s between calls instead of 6 s |
| `fred` | `FRED_API_KEY` | FRED / ALFRED series as known on the eve of T; without it, 0 request (DBnomics stays) |
| `piste` | `PISTE_CLIENT_ID` + `PISTE_CLIENT_SECRET` | Judilibre (Court of Cassation) and Legifrance; without the pair, 0 request |
| `openrouter`, `gemini`, `mistral`, `openai` | `OPENROUTER_API_KEY`, ... | contradictor families through an API (paid per call) |
| `s2`, `openaire` | `S2_API_KEY`, `OPENAIRE_TOKEN` | no effect today: engines not wired |

**PISTE** (law): register at https://piste.gouv.fr/, create an application, subscribe it to the Judilibre and Legifrance
APIs (production) and accept their terms; then `setup_keys.py piste` asks for the Client ID and the Client Secret. A
"not subscribed" line means the application lacks the API subscription. The PISTE engines are tested offline and **not yet
verified on the live service**.

Where to obtain each key, and the exact rules: [KEYS.md](KEYS.md). Set `VP_CONTACT` to a team or project address (never a
personal one) for the user agent that some sources ask for ([ACCESS-POLICY.md](ACCESS-POLICY.md)).

## 6. Costs and limits

| Run | Measured cost (model usage) |
|---|---|
| academic question, standard mode, Claude Code | about 3 USD (2.8 to 3.0 USD measured, verification included) |
| long legal texts | up to about 10 USD (the verifier reads long decisions whole) |
| code study with the whole reading | about 7 USD |
| full-text verification | extra; the example run: about 2.5 USD of research + about 9 USD of verifier, against 2.99 USD in total with defaults |
| audit mode | 6 to 7 times the standard mode |
| Codex CLI on a subscription | 0 USD metered; same number of gateway calls |

The searches stop on saturation, not on a budget; each plugin caps gateway calls (`cap: 60`) and the verifier has its own
pool (`verifier.call_cap`, 60). In non-interactive Claude Code runs, cap spending with `--max-budget-usd`.

Honest limits:
- **No public benchmark.** The figures come from small private benches (3 to 50 cases; often n = 1 per configuration); they
  cannot be reproduced from this repository.
- The skill does not find more than the reference deep-research method it rewrites (equal recall); its value is the
  downstream verification (-4.2 points of false claims, 50 questions), the whole reading on code and the plugins' rules.
- **HUDOC** may answer with a bot challenge depending on your network: the engine then returns `blocked` /
  `bot_challenge` after one request, with no workaround, and the report states that ECHR coverage was not observable.
- **PISTE** (Judilibre, Legifrance) is not verified on the live service.
- Sources without an API are declared in the plugins but not wired; `sources` lists them as `not_wired`.
- DBnomics serves current, revised values (marked `as_of: "now"`); only FRED/ALFRED gives values as known before T.
- A "Not found" in prior-art mode is not a proof of absence. The reports are research aids, not legal, financial or
  medical advice.

## 7. Running the tools by hand

All tools run from any directory, standard library only; each prints its usage with `--help`. `--plugin` takes a path or a
bare name (`cs-ai`). The gateway needs network; the other commands below are offline.

**Gateway** (date-bounded access; a state directory keeps the journal, cache and call counter):

```
python3 -I "$SKILL/tools/gateway.py" --plugin cs-ai --T 2026-10-26 --run try --state /tmp/vp-state sources
python3 -I "$SKILL/tools/gateway.py" --plugin cs-ai --T 2026-10-26 --run try --state /tmp/vp-state search-arxiv "retrieval augmented generation" --n 3
python3 -I "$SKILL/tools/gateway.py" --T 2026-10-26 --run try --state /tmp/vp-state read arxiv:1706.03762
```

Other commands: `citing <id>`, `references <id>`, `related <id>`; identifiers are `doi:`, `pmid:`, `arxiv:`, `celex:`,
`ecli:`, `nct:`, `hudoc:` and the others listed by `--help`.

**Verifier** (calls a model through your host CLI: `claude -p`, or `codex exec` with `VP_HOST=openai`):

```
python3 -I "$SKILL/tools/verifier.py" verify --card card.json --out verdicts.json \
    --T 2026-10-26 --plugin cs-ai --run try --state ./state --sources ./sources --filter
python3 -I "$SKILL/tools/verifier.py" check verdicts.json ./sources      # fragment check only, offline
```

Add `--fulltext` for the full-text reading, `--model M` to choose the model (default: the host CLI's default).

**End of run** (validation, retraction check, law checks, exports, in one command):

```
python3 -I "$SKILL/tools/finish_run.py" <dir> --T 2026-10-26 --plugin cs-ai
python3 -I "$SKILL/tools/finish_run.py" <dir> --offline --prisma --followups
```

Each step prints `ok`, `problems` or `skipped` and never stops the others; the exit code is 0 only when validation passed.
`--offline` takes the retraction check from the cache. For a law run, pass `--plugin law`.

**Exports and checks alone**:

```
python3 -I "$SKILL/tools/validate_card.py" <dir>          # empty output or "OK" = valid
python3 -I "$SKILL/tools/export_report.py" <dir> --pdf    # REPORT.html, and REPORT.pdf if WeasyPrint, Chromium, wkhtmltopdf or pandoc is installed
python3 -I "$SKILL/tools/export_data.py" <dir>            # studies.csv, references.bib / .ris / .json, passages.json
python3 -I "$SKILL/tools/living_diff.py" <old dir> <new dir>   # UPDATE.md and update.json
```

To try them without a run, copy `examples/report-cs-ai/` to a scratch directory and run `finish_run.py <copy> --offline`.

## 8. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| The host refuses a command | The skill runs one bare script per shell call (`python3 -I <skill>/tools/<script> ...`, no `&&`, pipes or `cd`) and retries a denied call once. Allow that pattern in your host's permissions; for `claude -p`, the README shows `--allowedTools "Bash(python3 -I $SKILL/tools/*)" Read Write Agent Glob Grep Skill`. |
| `key refused` from `setup_keys.py`, or `key_invalid` in the report | The provider rejected the key: the run goes on without it (call retried once without the key, key dropped for the run). Copy the key again whole and run `setup_keys.py <name> --check`. PISTE "not subscribed": subscribe the application to the API on piste.gouv.fr. |
| A source is `skipped`, `rate_limited`, `blocked` or `provider_error` | Read the "Source coverage" block: a missing key (install it, section 5), a quota (OpenAlex without key falls back to Crossref), a bot challenge (HUDOC: no workaround), or a slow provider (a first EUR-Lex query can take 60-90 s). The run continues with the other sources. |
| `claude -p` run ends with no `result.json` | Background sub-agents were killed after an idle delay. Launch with `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0` (README, "Claude Code"). |
| Claims left UNVERIFIED, "CAP reached" | The call cap stopped further readings; the report flags what was not verified. Rerun the question in a new directory if you need them checked. |
| `validate_card.py` reports check 13 | The end steps did not run on the current files: run `finish_run.py <dir>`. |
| Validation still fails after the run | The assistant corrects and reruns `finish_run.py` three times at most, then delivers with the remaining deviations listed. Read them before using the report. |
| Codex: every gateway call fails with a transport error | Codex's sandbox blocks the network: launch `codex -c sandbox_workspace_write.network_access=true`, or `codex exec -s workspace-write -c sandbox_workspace_write.network_access=true`, or set it in `~/.codex/config.toml`. |
| Codex: "bwrap: No permissions to create a new namespace" | The machine forbids unprivileged user namespaces, which Codex's sandbox needs. Enable them on the host; do not bypass the sandbox. Without a working sandbox the verifier cannot read its files and every claim stays UNVERIFIED (flagged, never passed). |
| Codex: the verifier calls `claude` | Export `VP_HOST=openai` in the shell that launches Codex. |
| Codex does not list the skill | Add the `AGENTS.md` block given in the README, which points to `SKILL.md`. |

## 9. Adding your own source

- A new source is one file, `tools/sources/<name>.py`, copied from `tools/sources/_TEMPLATE.py`; the date barrier, access
  policy, keys and tests it must respect are in [CONTRIBUTING.md](CONTRIBUTING.md). A new discipline is one file
  `plugins/<discipline>.md` copied from `plugins/_TEMPLATE.md` (README, "Adding a plugin").
- **Your own sources, outside the repository**: put the file in `~/.config/vp/sources/` and set `VP_USER_SOURCES=1`
  (it is Python code the gateway runs, so loading is opt-in). The gateway announces on stderr which user sources it loaded.
- **Local documents**: [`examples/user-sources/local_docs.py`](examples/user-sources/local_docs.py) searches your own `.txt`
  and `.md` files (and `.pdf` when `pdftotext` is installed), dated from their header (`date:`) or else the file date, under
  the same date barrier. Install it in three steps:

  ```
  mkdir -p ~/.config/vp/sources
  cp "$SKILL/examples/user-sources/local_docs.py" ~/.config/vp/sources/
  export VP_USER_SOURCES=1 VP_LOCAL_DOCS=/path/to/your/documents
  python3 -I "$SKILL/tools/gateway.py" --T 2026-10-26 --run try --state /tmp/vp-state search-local-docs "your words" --n 5
  ```

  To use it in a plugin's runs, add `local-docs` to that plugin's `engines:` line and `access: local-docs=local`; without
  a plugin every wired engine is available. Documents are read as data, never as instructions.
