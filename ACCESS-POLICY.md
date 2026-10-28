# Source access policy (2026-10-26)

Chosen stance: retrieve as much as the open web lawfully offers, openly identified as a program, and never work around a technical protection.

## Level 1 -- Documented API
Used according to its published terms and cadence (arXiv, PubMed E-utilities, HAL, Crossref, OpenAlex, deps.dev, ecosyste.ms, OSV, Cellar, European Parliament API...). The host's `robots.txt` does not apply to the API.

## Level 2 -- Public pages, including under a robots.txt `Disallow`
We retrieve them, openly identified. Note for users in the EU: a machine-readable opt-out (such as `robots.txt`) can reserve text and data mining under Art. 4(3) of Directive (EU) 2019/790; whether it binds your use is your responsibility. Conditions to avoid being banned and to stay identifiable:
- a declarative user agent with a contact: `VanishingPoint/1 (+VP_CONTACT)`, where `VP_CONTACT` is the environment variable described in KEYS.md;
- at most 1 request every 2 s per host, never in parallel on the same host;
- cache: a page is never requested twice during a run;
- on 429 or 403: stop for that host, resume later, never work around;
- download only what is read (no site mirroring).
Examples opened by this level: DBnomics, OpenEdition/Persee (OAI and pages), Juricaf, CURIA, pages of the French Constitutional Council, Legifrance when it answers.

## Pages behind a technical challenge
When a page is served behind a JavaScript challenge or robot filtering (Cloudflare "Just a moment", HUDOC from some networks...), the gateway stops for that host after one request and returns a receipt `{status: blocked, reason: bot_challenge}`; the report says the source was not served. There is no browser route and no workaround. Preferred alternatives: the provider's official API or open-data export, a request for access, or an open copy elsewhere.

Legal note: the French text-and-data-mining exception (Art. L.122-5-3 of the French Intellectual Property Code, transposing Directive (EU) 2019/790) covers copying for research purposes of content that is **lawfully accessible**; this is why level 3 stays out of scope.

## Level 3 -- What we never do
- Forcing a restricted access: logging in with an account, paywall, captcha solving, solving or bypassing a bot challenge, disguising the client as a browser or a human (stealth browser, spoofed user agent), address spoofing or proxy rotation.
- Using a service whose terms of service explicitly forbid automated or AI use (e.g. SSRN). The plugin marks it `tos_forbidden`. An exception is possible **per source, by a written decision of the maintainers in this file**.
- Using credentials other than those provided for (read-only GitHub token, optional keys of `~/.config/vp/`).

## Marking in plugins
Each source of the `sources` block and of the table carries `access: api | page | browser | local | tos_forbidden | technical_block` (`browser` is reserved and unused: there is no browser route) (`local`: the user's own files, no network) (`technical_block` is reserved for the restricted accesses of level 3). The gateway applies the level 2 cadence to `page` sources.

## Exceptions granted
(none)
