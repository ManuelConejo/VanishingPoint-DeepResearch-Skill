# Contributing a source

VanishingPoint reads documents only through its dated gateway (`tools/gateway.py`). Each search source lives in **one file**,
`tools/sources/<name>.py`. That file holds the source's `SOURCE` declaration and its code. The registry
(`tools/sources/__init__.py`) builds everything else from it:

- the gateway's engines, commands, options, host pacing, identifier routing and citation chaining;
- `check_keys.py` and `setup_keys.py`;
- `validate_card.py`, `validate_result.py`, `verifier.py`, `export_data.py` and `law_checks.py`.

No other file keeps a list of sources. Standard library only, English only.

## 1. Add a source in one file

1. Copy `tools/sources/_TEMPLATE.py` to `tools/sources/<name>.py`. Files whose name starts with `_` are helpers or models, never sources.
2. Write `search_<name>(q, n, B, **options)`. It returns `(items, total_or_note)`. Each item is a dict with at least
   `id` (`<prefix>:<value>`), `title`, `year` and the dates it was checked on.
3. Write `read_<name>(ident, B)`. It receives the stripped `prefix:value` and returns a record, or `{'refusal': '...'}`. It never returns an empty dict.
4. Fill in `SOURCE`. The template comments every field:
   - `name`, `engines` (or `commands` for a code engine) and `ids`: identifier prefix, result form, export type, and `law_form` for a law identifier;
   - `read`, plus `citing` / `references` / `related`. Each is a callable or a "not served" message. Leave it out to hand the
     identifier to the default DOI chaining;
   - `plugins` (informative), `access`, `hosts` (pacing and stop codes), `terms`, `barrier`, optional `as_of` and `key`.
5. List the engine in the ```sources block of the plugin(s) that should use it (`engines:`, `access:`, and `keys:` if it has a key).
   The block format does not change.
6. Run the test suite (section 6).

Names, engines, commands, identifier prefixes and served names must be unique. A duplicate is a `RegistryError` at import, naming
both files. Two sources may share a host, but only with the same pacing.

Two sources may share one file only when they truly share code. Examples: `piste.py` (Judilibre + Legifrance, one OAuth client)
and `biorxiv.py` (bioRxiv + medRxiv, one API). Shared helpers of a family go in an `_<family>.py` module (`_cs.py`, `_series.py`).

## 2. The date barrier (non-negotiable)

Every source answers as if the question were asked on date **T**. Nothing dated on or after T may come out.

- **Filter on the provider side at the eve of T** whenever the API allows it (`B.eve`, and `B.start` for a lower bound). Then
  **recheck locally**: `B.ok(doi, *dates, title=...)`, `extra_ok(B, ids, dates, titles)` or `law_ok(...)`. They also apply the
  forbidden identifiers and titles, and they count exclusions.
- Check **every** date that can be later than the work itself: publication **and** indexing, deposit, last version, upload, vintage.
- **No usable date means refused.** A `None` date fails `B.ok`. Never guess one.
- **Never fabricate precision.** A year alone goes through `year_before_T` (kept only when strictly before the year of T). A partial
  date is read as its upper bound (`date_upper`). Do not turn `2024` into `2024-01-01`.
- Fields that changed after T (status, validity, counts) are **masked**, never served. See `osv.py`, `clinicaltrials.py` and `eurlex.py`.
- Data that exist only as current values (live counts, revised series) are marked **`as_of: "now"`** on every record. Say so
  in `SOURCE['as_of']` (see `dbnomics.py`, `usage.py`).
- Items that carry a DOI pass only when Crossref attests deposit **and** publication before T (`crossref.doi_recheck`).
- Describe the barrier in `SOURCE['barrier']` in one or two sentences, as `pubmed.py` and `hal.py` do.

## 3. Access policy

Follow [ACCESS-POLICY.md](ACCESS-POLICY.md). `access` is `api` (a documented API), `page` (public pages, level 2), `browser`, or `local` (the user's own files, no network).

- A `page` source paces at **2 s or more** per host and stops at once on **403/429** (`hosts: {'h': {'interval': 2.0, 'stop': (403, 429)}}`).
- `fetch` caches every answer, paces each host and identifies itself (`VP_CONTACT`).
- Never work around a challenge, a login or a paywall (level 3).
- Never wire a service whose terms forbid automated or AI use (`tos_forbidden`).
- Write the provider's terms or licence, as published, in `terms`.

## 4. Keys

Every key is optional for the skill. A source that cannot work without its key is **skipped with 0 request** and returns a receipt
`{"status": "skipped", "reason": "credential_missing" | "not_configured"}`. It never reports "nothing found". See
`fred.py` (`DataSkip`) and `piste.py` (`PisteSkip`).

- Declare the key in `SOURCE['key']`:
  - `vars`;
  - `send`: `query:<param>` | `bearer` | `header:<Name>` | `oauth-client-credentials`;
  - `hosts`: the **only** hosts the key may reach;
  - `without`: `degraded` | `skipped`;
  - `reason`, `free`, `url`;
  - optionally `suggest`, `labels`, `check`, `rejected`, `interval_with_key`.

  `check_keys.py` and `setup_keys.py` read it from there. Also add the key to the table in `KEYS.md`, for humans.
- Resolve the key with `key(NAME)` or `live_key(NAME)`. Never read the environment yourself.
- **A key never appears in a URL**, except as the declared query parameter sent to a declared host.
- **A key never appears** in a receipt, the journal, an error message, the cache or a printed line. Only names go to
  `keys-invalid.json`. A key the provider rejects is marked with `sc.mark_invalid(STATE, NAME)`. The run goes on without it and every
  answer carries `key_invalid: [NAME]`. For an `api_key=` parameter, `rejected` makes `fetch` do this for you.
- `check(state)` (used by `setup_keys.py --check`) sends one minimal live request. It returns `'ok'` or `'refused'`, or
  `{label: outcome}` for a source with several services.

## 5. User sources (your own, outside the repository)

Put the file in `~/.config/vp/sources/<name>.py` and import the helpers with `from sources._common import ...`. Then set
**`VP_USER_SOURCES=1`**.

- Loading is opt-in: the file is Python code that the gateway runs.
- On every run, the gateway prints on stderr the user sources it loaded, or the files it ignored because the flag is not set.
- `gateway.py sources` lists them under `user_sources`.
- A user source follows the same contract. It cannot replace a built-in name, engine or prefix.
- A source that reads only local files declares `access: 'local'` and no host (`hosts: {}`): it makes no request.
- Worked example: [`examples/user-sources/local_docs.py`](examples/user-sources/local_docs.py) (the user's own documents: txt, md, and pdf
  when `pdftotext` is installed; date from the header or the file; skipped with a `not_configured` receipt until a folder is set).
  Its offline test is `tests/test_user_source_local_docs.py`.

## 6. Tests

Add `tests/test_engines_<name>.py` with a stubbed `gateway.fetch` (see `test_engines_extra.py`, `test_engines_finance.py`). At least:

- a result dated on/after T is refused and counted;
- an undated result is refused;
- the provider-side filter is at the eve of T (assert on the URL);
- `read` of a post-T record is refused;
- for a keyed source: no key means 0 request (`skipped`) or no credential sent (`degraded`).

`tests/test_sources_contract.py` checks every registered source automatically:

- the declaration is complete;
- names and prefixes are unique;
- plugin `access:` lines match the declarations;
- key hosts are declared;
- every prefix is routed by `read`;
- without its key, a source makes 0 request to the key's hosts;
- a fake key never leaks and goes only to its declared hosts in the declared way.

Run the suite as a normal user (not root), offline, from the skill directory:

```
for t in tests/test_*.py; do python3 -I "$t"; done        # test_code_capsule.py needs pytest: python3 -m pytest -q tests/test_code_capsule.py
```

Tests must not create anything inside the skill directory. Use `tempfile` and set `gateway.STATE` (or pass `state=` to `Gateway`).
Setting `gateway.fetch`, `gateway.STATE`, `gateway.piste_http` or `gateway._PISTE_OPENER` in a test reaches every source module.
