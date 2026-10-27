# Context capsule: example-project@0123456789ab

This is a hand-written model of the file that `tools/code_capsule.py` produces for a host repository X pinned at one
commit (plugins/code.md, section "Context capsule"). The generated part (Identity, License, Seam map, Entry points,
Tests, Contribution registry, Meta) is computed from the repository tree; the first block is what the owner of X fills
by hand before a run. Values here are placeholders, not a real project.

## To fill before use

- target_seam: TO BE FILLED BY THE OWNER  (1 to 3 seams, path:line@SHA on the X side, what happens there today)
- intention: TO BE FILLED BY THE OWNER  (measurable: throughput, invariant, guarantee, cost)
- refusals: TO BE FILLED BY THE OWNER  (core, Gate, licences, dependencies; a missing refusal = implicit permission)
- reviewed_by_owner: no (TO BE FILLED BY THE OWNER: yes + date after review)
- request_date: TO BE FILLED BY THE OWNER (= T)
- mode: TO BE FILLED BY THE OWNER (Y given | need only)
- Y: TO BE FILLED BY THE OWNER (repository@SHA, licence read)

Review by the owner: plugins/code.md, section Context capsule (5 points). Not reviewed = report labelled "capsule not reviewed".

## Identity

- X: /path/to/example-project@0123456789abcdef0123456789abcdef01234567
- commit_date: 2026-01-01T00:00:00+00:00
- tree_sha256: 0000000000000000000000000000000000000000000000000000000000000000
- files: 0; bytes: 0

## License

- LICENSE MISSING: read before any borrowing

## Seam map (0 modules)

| language | module | files | bytes |
|---|---|---|---|

## Entry points


Limit: lexical parsers only: entry points computed at runtime (dynamic setup.py) are not seen

## Tests

- tests/: 0 test files
- total test files: 0

## Contribution registry

No registry (contributions.jsonl missing at this SHA, --registry not given).

## Meta

- generated_utc: 2026-01-01T00:00:00+00:00; tool: code_capsule.py
