# SPDX-License-Identifier: Apache-2.0
"""ECLI resolver (no search engine): ecli:ECLI:EU:... through Cellar (eurlex), ecli:ECLI:FR:... through the administrative courts
open data (justice-administrative), ecli:ECLI:CE:ECHR:... through HUDOC (hudoc)."""
from sources._common import LAW_NO_CHAIN, RELATED_ONLY, value
from sources.eurlex import read_ecli_eu
from sources.hudoc import read_ecli_echr
from sources.justice_administrative import read_ecli_fr


def read_ecli(ident, B):
    v = value(ident)
    v = v if v.upper().startswith('ECLI:') else 'ECLI:' + v
    if v.upper().startswith('ECLI:EU:'): return read_ecli_eu(v, B)
    if v.upper().startswith('ECLI:FR:'): return read_ecli_fr(v, B)
    if v.upper().startswith('ECLI:CE:ECHR:'): return read_ecli_echr(v.upper(), B)
    return {'refusal': 'ECLI of an order not served (EU, FR and ECHR only)'}


SOURCE = {
    'name': 'ecli', 'order': 55,
    'ids': [{'prefix': 'ecli', 'form': r'(ECLI:)?[A-Z]{2}:[A-Z0-9.]{1,7}:\d{4}:[A-Z0-9.]{1,25}', 'law_form': r'ECLI:[A-Z]{2}:[A-Z0-9.]{1,7}:\d{4}:[A-Z0-9.]{1,25}',
             'export': 'case', 'export_rank': 50}],
    'read': read_ecli, 'citing': LAW_NO_CHAIN, 'references': LAW_NO_CHAIN, 'related': RELATED_ONLY,
    'plugins': ('law',), 'access': 'api',
    'hosts': {'publications.europa.eu': {}, 'opendata.justice-administrative.fr': {}, 'hudoc.echr.coe.int': {}},   # paced by the eurlex, justice-administrative and hudoc declarations
    'terms': 'see eurlex (EU), justice-administrative (FR) and hudoc (ECHR)',
    'barrier': 'the barrier of the source that serves the court (eurlex, justice-administrative or hudoc)',
}
