# SPDX-License-Identifier: Apache-2.0
"""Shared helpers of the CS sources (hf, standards, proceedings; v0.4.6, plugins/cs-ai.md). Never a source itself."""
import html
import json
import re
from sources._common import CFG, STATE, tokens


# ---------------------------------------------------------------- CS engines (v0.4.6, plugins/cs-ai.md): hf-models, hf-datasets, standards, proceedings; command related
# All keyless (probes 2026-10-28). Index files (RFC index, PEP index, W3C list, ACL bib, PMLR volume feeds, CVF listings) are fetched once,
# kept in the fetch cache, parsed once into <state>/cs-index/<name>.json; the title search is local. Hosts stop at once on 403/404/429.

CS = CFG.get('cs_engines') or {}
CS_STOP = (401, 403, 404, 410, 429)   # every CS host stops at once on these codes
CS_NO_CHAIN = 'citation chaining not served for hfmodel:, hfdataset:, rfc:, pep:, w3c:, acl:, pmlr:, cvf: identifiers (read the DOI or arXiv id)'


def cs_index(name, build):
    """Parsed index <state>/cs-index/<name>.json (built once from cached index files; not T-dependent: the barrier is applied per item)."""
    f = STATE / 'cs-index' / (re.sub(r'[^\w.-]', '_', name) + '.json')
    if f.exists(): return json.loads(f.read_text())
    x = build()
    if x: f.parent.mkdir(parents=True, exist_ok=True); f.write_text(json.dumps(x))   # an empty parse is never kept
    return x


def cs_match(q, recs, text):
    """Local title search: every query word (3 letters or more) present in text(rec); -> [(words in the title, rec)]."""
    qt = tokens(q)
    if not qt: return []
    out = []
    for r in recs:
        tt = tokens(r.get('title') or '')
        if qt <= tt or qt <= tt | tokens(text(r)): out.append((len(qt & tt), r))
    return out


def cs_text(s, k=6000): return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', s or '')).split())[:k]
