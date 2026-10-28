# Source access policy (2026-10-26)

Chosen stance: a permissive approach that retrieves as much as possible, even if borderline. It replaces the earlier rule "respect robots.txt".

## Level 1 -- Documented API
Used according to its published terms and cadence (arXiv, PubMed E-utilities, HAL, Crossref, OpenAlex, deps.dev, ecosyste.ms, OSV, Cellar, European Parliament API...). The host's `robots.txt` does not apply to the API.

## Level 2 -- Public pages, including under a robots.txt `Disallow`
We retrieve them. `robots.txt` is a convention, not an obligation. Conditions to avoid being banned and to stay identifiable:
- a declarative user agent with a contact: `VanishingPoint/1 (+VP_CONTACT)`, where `VP_CONTACT` is the environment variable described in KEYS.md;
- at most 1 request every 2 s per host, never in parallel on the same host;
- cache: a page is never requested twice during a run;
- on 429 or 403: stop for that host, resume later, never work around;
- download only what is read (no site mirroring).
Examples opened by this level: DBnomics, OpenEdition/Persee (OAI and pages), Juricaf, CURIA, pages of the French Constitutional Council, Legifrance when it answers.

## Level 2 bis -- Public pages behind a technical challenge
(added 2026-10-26, "including through specific circumvention tools"; research context, French text-and-data-mining exception)

When a page is public (no account, no payment) but served behind a JavaScript challenge or robot filtering (Cloudflare "Just a moment", HUDOC, Legifrance HTML...), it is retrieved with a driven browser (Playwright, stealth mode), as a human reader would do. Same cadence and same cache as level 2; volume limited to the pages read; marked `access: browser`.

Legal note: the French text-and-data-mining exception (Art. L.122-5-3 of the French Intellectual Property Code, transposing Directive (EU) 2019/790) covers copying for research purposes of content that is **lawfully accessible**; this is why level 3 stays out of scope.

## Level 3 -- What we never do
- Forcing a restricted access: logging in with an account, paywall, captcha solving by a third-party service, address spoofing or proxy rotation.
- Using a service whose terms of service explicitly forbid automated or AI use (e.g. SSRN). The plugin marks it `tos_forbidden`. An exception is possible **per source, by a written decision of the maintainers in this file**.
- Using credentials other than those provided for (read-only GitHub token, optional keys of `~/.config/vp/`).

## Marking in plugins
Each source of the `sources` block and of the table carries `access: api | page | browser | local | tos_forbidden | technical_block` (`local`: the user's own files, no network) (`technical_block` is reserved for the restricted accesses of level 3). The gateway applies the level 2 cadence to `page` sources.

## Exceptions granted
(none)
