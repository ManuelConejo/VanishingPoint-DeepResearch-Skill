# SPDX-License-Identifier: Apache-2.0
"""OpenCitations Index API v2 (keyless, data CC0): search-opencitations "<DOI>" -> the works citing that DOI and the works it cites,
each dated before T. Also the complement of the DOI chaining (doi.py citing / references): the OpenCitations works not already listed are
appended after the existing ones (config linked_sources.opencitations_complement)."""
import re
import urllib.parse
from sources._common import CFG, date_upper, jget
from sources.crossref import crossref_batch

API = 'https://api.opencitations.net/index/v2/'
DOI = re.compile(r'10\.\d{4,9}/\S+')
MAX = int(CFG['linked_sources']['opencitations_max'])
COMPLEMENT = bool(CFG['linked_sources']['opencitations_complement'])


def _doi_in(field):
    """'omid:br/061 doi:10.x/y pmid:1' -> '10.x/y' or None (a work without DOI cannot be rechecked on Crossref: refused)."""
    return next((t[4:] for t in str(field or '').split() if t.startswith('doi:') and DOI.fullmatch(t[4:])), None)


def oc_links(doi, op):
    """Raw OpenCitations rows (citations | references) of a DOI (one request; the cap applies to the rows kept, after the dates)."""
    r = jget(API + op + '/doi:' + urllib.parse.quote(doi, safe='/'))
    return r if isinstance(r, list) else []


def oc_citing(doi, B):
    """Works citing `doi`, dated < T: the citing work's publication (`creation`, partial date = upper bound) < T, then Crossref deposit AND
    publication < T. Rows without a DOI or a date are refused and counted. -> (items, rows read)."""
    rows = oc_links(doi, 'citations')
    dois = []   # citing DOIs dated < T, in the provider's order
    for c in rows:
        d, cr = _doi_in(c.get('citing')), date_upper(c.get('creation'))
        if d and cr and cr < B.T and d.lower() not in [x.lower() for x in dois]: dois.append(d)
    dois = dois[:MAX]                         # linked_sources.opencitations_max works rechecked on Crossref
    out = [dict(x, via='opencitations') for x in crossref_batch(dois, B)]
    B.excluded += len(rows) - len(out)
    return out, len(rows)


def oc_references(doi, B):
    """Works cited by `doi` (the citing work itself must be dated < T by the caller): each cited DOI rechecked on Crossref (deposit AND
    publication < T). -> (items, rows read)."""
    rows = oc_links(doi, 'references')
    dois = []
    for c in rows:
        d = _doi_in(c.get('cited'))
        if d and d.lower() not in [x.lower() for x in dois]: dois.append(d)
    dois = dois[:MAX]
    out = [dict(x, via='opencitations') for x in crossref_batch(dois, B)]
    B.excluded += len(rows) - len(out)
    return out, len(rows)


def complement(out, n, fn, doi, B):
    """Existing chaining items first, unchanged; then OpenCitations items not already listed, while there is room under n. A failure of
    OpenCitations never loses the existing answer."""
    if not COMPLEMENT or not doi or len(out) >= n: return out
    try: extra, _ = fn(doi, B)
    except Exception: return out
    have = {str(x.get('id') or '').lower() for x in out} | {'doi:' + str(x['doi']).lower() for x in out if x.get('doi')}   # pmid: items carry their DOI
    return out + [x for x in extra if x['id'].lower() not in have][:n - len(out)]


def search_opencitations(q, n, B):
    """`<DOI>` (citing and references), `citing:<DOI>` or `references:<DOI>`. The DOI itself must be dated < T on Crossref."""
    m = re.fullmatch(r'\s*(?:(citing|references):)?\s*(?:doi:)?(10\.\d{4,9}/\S+)\s*', str(q or ''), re.I)
    if not m: return [], 'expected a DOI, citing:<DOI> or references:<DOI>, e.g. search-opencitations "10.1186/1756-8722-6-59"'
    op, doi = (m.group(1) or '').lower(), m.group(2)
    if not crossref_batch([doi], B): B.excluded += 1; return [], 'document after T, forbidden or deposit not attested'
    out, notes = [], []
    if op in ('', 'citing'):
        c, k = oc_citing(doi, B); out += [dict(x, relation='citing') for x in c]; notes.append(f'{k} citing rows (all dates), {len(c)} before T')
    if op in ('', 'references'):
        r, k = oc_references(doi, B); out += [dict(x, relation='reference') for x in r]; notes.append(f'{k} reference rows, {len(r)} dated before T')
    return out[:n], 'OpenCitations: ' + '; '.join(notes) + ' (Crossref recheck)'


SOURCE = {
    'name': 'opencitations', 'order': 22,
    'engines': {'opencitations': search_opencitations},
    'plugins': ('biology', 'cs-ai', 'finance', 'law'), 'access': 'api',
    'hosts': {'api.opencitations.net': {'interval': 0.4}},                 # published limit 180 requests/minute per IP (0.33 s): 0.4 s
    'terms': 'OpenCitations Index REST API v2 (University of Bologna), keyless (optional access token not used); data CC0',
    'barrier': 'the queried DOI dated < T on Crossref; citing works: creation date < T then Crossref deposit AND publication < T; cited works: '
               'Crossref deposit AND publication < T; rows without DOI or date refused',
}
