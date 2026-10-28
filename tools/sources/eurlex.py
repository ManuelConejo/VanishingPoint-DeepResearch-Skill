# SPDX-License-Identifier: Apache-2.0
"""EUR-Lex through the Publications Office Cellar (SPARQL + content negotiation): search-eurlex, read celex:<n>; EU ECLI read helper."""
import html
import json
import re
import urllib.error, urllib.parse, urllib.request
from sources._common import ProviderError, _before, date_upper, fetch, head_and_operative, law_ok
from sources._common import LAW_NO_CHAIN, RELATED_ONLY, value


CELLAR = 'https://publications.europa.eu/webapi/rdf/sparql'
CDM = 'PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>\nPREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n'
EU_LANG = 'http://publications.europa.eu/resource/authority/language/'
CELEX_FORM = r'[0-9][0-9A-Z()_.\-]{4,40}'


def sparql(q):
    """Cellar SPARQL (GET, JSON). HTTP 5xx or unreadable answer -> ProviderError (law.md: VECSL 500 = provider_error, not empty)."""
    try: r = json.loads(fetch(CELLAR + '?' + urllib.parse.urlencode({'query': q, 'format': 'application/sparql-results+json'})))
    except urllib.error.HTTPError as e:
        if e.code >= 500: raise ProviderError(f'provider_error: Cellar HTTP {e.code} (not an empty result)')
        raise
    except ValueError: raise ProviderError('provider_error: Cellar answer is not JSON (not an empty result)')
    except (TimeoutError, urllib.error.URLError) as e: raise ProviderError(f'provider_error: Cellar unreachable or timeout ({str(e)[:60]})')
    return [{k: v.get('value') for k, v in b.items()} for b in r.get('results', {}).get('bindings', [])]


def eu_kept(celex):
    """Sectors 0 (consolidated), 3 (legislation), 6 (case law); Advocate General opinions (6....CC), _RES/_INF and the OJ notices of a judgment
    (6....CA/TA/FA, a duplicate of the ruling, not its text) set aside (law.md 1-2)."""
    return bool(re.match(r'^[036]', celex)) and not re.match(r'^6\d{4}(CC|[CTF]A)', celex) and '_RES' not in celex and '_INF' not in celex


def eu_details(celexes):
    """Per CELEX (twins grouped): dates, entry into force, end of validity, flag, lastModificationDate, ECLI, both "declares void"
    predicates read from the voiding rulings with their dates. One property per UNION branch: no OPTIONAL join (the ELI trap)."""
    if not celexes: return {}
    vals = ' '.join('"%s"^^xsd:string' % c for c in celexes)
    q = CDM + ('SELECT DISTINCT ?celex ?k ?v ?d WHERE { VALUES ?celex { %s } ?w cdm:resource_legal_id_celex ?celex .\n'
               '{ ?w cdm:work_date_document ?v BIND("date" AS ?k) } UNION { ?w cdm:resource_legal_date_entry-into-force ?v BIND("eif" AS ?k) }\n'
               'UNION { ?w cdm:resource_legal_date_end-of-validity ?v BIND("eov" AS ?k) } UNION { ?w cdm:resource_legal_in-force ?v BIND("flag" AS ?k) }\n'
               'UNION { ?w <http://publications.europa.eu/ontology/cdm/cmr#lastModificationDate> ?v BIND("lmd" AS ?k) } UNION { ?w cdm:case-law_ecli ?v BIND("ecli" AS ?k) }\n'
               'UNION { ?r cdm:case-law_declares_void_resource_legal ?w . ?r cdm:resource_legal_id_celex ?v . OPTIONAL { ?r cdm:work_date_document ?d } BIND("void" AS ?k) }\n'
               'UNION { ?r cdm:case-law_declares_void_by_preliminary_ruling_resource_legal ?w . ?r cdm:resource_legal_id_celex ?v . '
               'OPTIONAL { ?r cdm:work_date_document ?d } BIND("void_pr" AS ?k) } }') % vals
    out = {}
    for b in sparql(q):
        d = out.setdefault(b['celex'], {})
        d.setdefault(b['k'], []).append((b.get('v'), b.get('d')) if b['k'].startswith('void') else b.get('v'))
    return out


def eu_item(celex, titles, det, B):
    """Dated Cellar record. Barrier on every work_date_document of the CELEX (twins included). Validity metadata are post-T knowledge
    when the notice was modified on or after T: then only dates before T are served, the end of validity only when before T and no
    voiding ruling is dated on/after T (void ab initio is written after the fact), the current "in force" flag is masked."""
    ecli = (det.get('ecli') or [None])[0]
    tl = [t for _, t in sorted(titles)]
    if not eu_kept(celex) or not law_ok(B, [celex, 'celex:' + celex, ecli], det.get('date') or [None], tl): return None
    date = max(det['date']); lmd = max(det.get('lmd') or [''])
    fresh = bool(lmd) and date_upper(lmd) is not None and date_upper(lmd) < B.T
    voids = [(c, d, k) for k in ('void', 'void_pr') for c, d in det.get(k, [])]
    vb = [{'celex': c, 'date': d[:10], 'by_preliminary_ruling': k == 'void_pr'} for c, d, k in voids if _before(d, B) and c != celex]
    late_void = any(not _before(d, B) for _, d, _ in voids)
    eif = sorted(det.get('eif') or []); eov = sorted(det.get('eov') or [])
    keep = (lambda x: x) if fresh else (lambda x: _before(x, B))
    it = {'id': 'celex:' + celex, 'celex': celex, 'doi': None, 'title': ' '.join(tl[0].replace('#', ' - ').split()) if tl and tl[0] else None, 'year': date[:4], 'date': date[:10],
          'journal': 'EUR-Lex (Cellar)', 'type': 'decision' if celex[0] == '6' else 'text', 'tier': 'primary', 'order': 'EU', 'consolidated': celex[0] == '0',
          'in_force_from': keep(eif[0]) if eif else None, 'applies_from': keep(eif[-1]) if eif else None,   # applies_from: latest entry-into-force value
          'in_force_to': (eov[-1] if fresh else (_before(eov[-1], B) if not late_void else None)) if eov else None,   # inclusive in Cellar
          'in_force': ((det.get('flag') or [None])[0] if fresh else None), 'declared_void_by': vb,
          'validity': 'notice unchanged since before T' if fresh else 'notice modified on/after T: post-T validity masked (only dates before T kept)'}
    if celex[0] == '6':
        it.update(ecli=ecli, court=celex[5:7], set_aside_by=[v['celex'] for v in vb if not v['by_preliminary_ruling']])
    return it


def _eu_words(q):
    return [w for w in re.findall(r'\w+', q.lower()) if len(w) >= 3 and not w.isdigit()][:6]


def search_eurlex(q, n, B):
    """EUR-Lex Cellar SPARQL: title words (EN or FR expression), date of the act/ruling bounded in the query to [start, eve of T].
    Two queries (legislation 0/3, case law 6; otherwise recent rulings bury the acts), interleaved, then one details query."""
    words = _eu_words(q)
    if not words: return [], 'no usable title word (3 letters or more)'
    langs = ', '.join(f'<{EU_LANG}{x}>' for x in ('ENG', 'FRA'))
    order, titles, nrows = {'leg': [], 'cl': []}, {}, {}
    for part, sector in (('leg', '^[03]'), ('cl', '^6')):
        # bif:contains = Virtuoso free-text index on the titles (a CONTAINS(LCASE()) scan times out on the whole of Cellar, measured 2026-10-28)
        sq = CDM + ('SELECT DISTINCT ?celex ?date ?title ?lang WHERE { ?e cdm:expression_title ?title . ?title bif:contains "' + ' AND '.join(f"'{w}'" for w in words) + '" .\n'
                    f'?e cdm:expression_belongs_to_work ?w ; cdm:expression_uses_language ?lang . FILTER(?lang IN ({langs}))\n'
                    f'?w cdm:resource_legal_id_celex ?celex ; cdm:work_date_document ?date . FILTER(?date >= "{B.start}"^^xsd:date && ?date <= "{B.eve}"^^xsd:date)\n'
                    f'FILTER(REGEX(STR(?celex), "{sector}") && !REGEX(STR(?celex), "^6[0-9]{{4}}(CC|[CTF]A)") && !CONTAINS(STR(?celex), "_RES") && !CONTAINS(STR(?celex), "_INF"))\n'
                    '} ORDER BY DESC(?date) LIMIT 100')
        rows = sparql(sq); nrows[part] = len(rows)
        for r in rows:
            c = r['celex']
            if c not in titles: order[part].append(c); titles[c] = []
            titles[c].append((0 if r.get('lang', '').endswith('ENG') else 1, r.get('title')))
    k = max(n, 20)
    mix = [c for pair in zip(order['leg'][:k], order['cl'][:k]) for c in pair]
    mix = (mix + order['leg'][len(mix) // 2:k] + order['cl'][len(mix) // 2:k])[:k]
    det = eu_details(mix)
    out = [x for x in (eu_item(c, titles[c], det.get(c, {}), B) for c in mix) if x]
    return out[:n], (f"bounded: legislation {len(order['leg'])} CELEX ({nrows['leg']} title rows), case law {len(order['cl'])} CELEX ({nrows['cl']} rows); "
                     'LIMIT 100 each, most recent first; Cellar gives no count')


def read_celex(celex, B):
    """CELEX notice (dates, validity under the barrier) + start of the official text through Cellar content negotiation (XHTML, EN then FR);
    for a judgment longer than TEXT_HEAD, its operative part is appended (head_and_operative).
    EUR-Lex HTML (eur-lex.europa.eu) answers 202 with an empty body (bot challenge): not used (ACCESS-POLICY.md)."""
    if not re.fullmatch(CELEX_FORM, celex): return {'refusal': 'malformed CELEX'}
    if re.match(r'^6\d{4}CC', celex): return {'refusal': 'Advocate General opinion: excluded (law.non_binding, leakage risk)'}
    rows = sparql(CDM + 'SELECT DISTINCT ?title ?lang WHERE { ?w cdm:resource_legal_id_celex "%s"^^xsd:string . ?e cdm:expression_belongs_to_work ?w ; '
                  'cdm:expression_uses_language ?lang ; cdm:expression_title ?title . FILTER(?lang IN (<%sENG>, <%sFRA>)) }' % (celex, EU_LANG, EU_LANG))
    det = eu_details([celex]).get(celex)
    if not det: return {'refusal': 'not found'}
    it = eu_item(celex, [(0 if r.get('lang', '').endswith('ENG') else 1, r.get('title')) for r in rows], det, B)
    if not it: return {'refusal': 'after T, forbidden or excluded'}
    for lang in ('eng', 'fra'):
        try: x = fetch('https://publications.europa.eu/resource/celex/' + urllib.parse.quote(celex), headers={'Accept': 'application/xhtml+xml, text/html;q=0.9', 'Accept-Language': lang})
        except Exception: continue
        t = html.unescape(re.sub(r'<[^>]+>', ' ', re.sub(r'(?is)<(head|script|style)\b.*?</\1>', ' ', x.decode('utf-8', 'replace'))))
        t = ' '.join(t.split())
        if t:
            t, how = head_and_operative(t, celex[0] == '6')
            return dict(it, abstract=t, text_language=lang, text_source=f'Cellar (official text, {how})')
    return dict(it, abstract='(no text available from Cellar)')


def read_ecli_eu(ecli, B):
    if not re.fullmatch(r'ECLI:EU:[A-Z]{1,2}:\d{4}:[0-9A-Z.]{1,12}', ecli): return {'refusal': 'malformed EU ECLI (expected ECLI:EU:C:2014:238)'}
    rows = sparql(CDM + 'SELECT DISTINCT ?celex WHERE { ?w cdm:case-law_ecli "%s"^^xsd:string ; cdm:resource_legal_id_celex ?celex }' % ecli)
    cs = sorted({r['celex'] for r in rows if eu_kept(r['celex'])})
    return read_celex(cs[0], B) if cs else {'refusal': 'not found (or Advocate General opinion, excluded)'}


def read_eurlex(ident, B): return read_celex(value(ident), B)


def celex_type(ident, venue):
    """Sector 6 of a CELEX number = case law, else legislation."""
    return 'case' if ident.partition(':')[2][:1] == '6' else 'legislation'


SOURCE = {
    'name': 'eurlex', 'order': 50,
    'engines': {'eurlex': search_eurlex},
    'ids': [{'prefix': 'celex', 'form': r'[0-9CE]\d{4}[A-Z]{1,3}\d{1,5}[0-9A-Z()_.\-]*', 'law_form': r'[0-9CE]\d{4}[A-Z]{1,3}\d{1,5}[0-9A-Z()_.\-]*', 'export': celex_type, 'export_rank': 70}],
    'read': read_eurlex, 'citing': LAW_NO_CHAIN, 'references': LAW_NO_CHAIN, 'related': RELATED_ONLY,
    'plugins': ('law',), 'access': 'api',
    'hosts': {'publications.europa.eu': {'interval': 2.0, 'timeout': 90, 'stop': (400, 500, 'timeout')}},   # Cellar 500 = provider_error; first free-text query ~60-90 s
    'terms': 'EU Publications Office Cellar (SPARQL endpoint and content negotiation), EU reuse policy; eur-lex.europa.eu HTML is not used (bot challenge)',
    'barrier': 'provider side: date of the act / ruling bounded in the SPARQL query to [start, eve of T]; local: every work_date_document < T; '
               'when the notice was modified on/after T, validity metadata are masked to dates before T (no post-T in-force flag, end of validity '
               'or void ruling); no usable date -> refused',
}
