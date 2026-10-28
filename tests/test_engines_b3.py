#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""AI and code engines added on 2026-10-28: openreview, zenodo, hal-info (plugins/cs-ai.md), paper-code declared by cs-ai, usage
(ecosyste.ms, plugins/code.md), Stack Exchange left tos_forbidden, check_keys "served by" display. Everything offline (fetch and the
code client transport replaced). Per engine: only the record dated before T is served (after T, day T, partial date at the year of T,
forbidden id or title, no date: refused); provider-side bound on the eve of T when the provider has one; no key nor e-mail in any URL.
Run: python3 -I tests/test_engines_b3.py
"""
import datetime as dt, json, os, pathlib, re, sys, tempfile, unittest, urllib.error, urllib.parse
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools')); import gateway as gw, code_sources as sc, check_keys as ck   # noqa: E702

T = dt.date(2024, 3, 15); V, F = '2024-03-14', '2024-03-16'
FORBID_T = 'Forbidden landmark survey of retrieval augmented generation'


def barrier(): return gw.Barrier(T, forbidden_dois=['10.1/forbid', 'forbidID01'], forbidden_titles=[FORBID_T])


def ms(day, h=12): return int(dt.datetime.fromisoformat(day + f'T{h:02d}:00:00+00:00').timestamp() * 1000)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); gw.STATE = pathlib.Path(self.tmp.name); self.fetch0 = gw.fetch; self.urls = []
        self.contact = os.environ.get('VP_CONTACT'); os.environ['VP_CONTACT'] = 'someone@example.org'   # must never reach a URL

    def tearDown(self):
        gw.fetch = self.fetch0; self.tmp.cleanup()
        if self.contact is None: os.environ.pop('VP_CONTACT', None)
        else: os.environ['VP_CONTACT'] = self.contact

    def clean(self):
        self.assertTrue(self.urls)
        for u in self.urls: self.assertFalse('@' in u or re.search(r'api_key|apikey|token|key=|mailto', u, re.I), u)


# ---------------------------------------------------------------- OpenReview

def note(i, title, cdate=V, **kw):
    n = {'id': i, 'forum': i, 'replyto': None, 'invitation': 'ICLR.cc/2024/Conference/-/Blind_Submission', 'readers': ['everyone'],
         'content': {'title': title, 'abstract': 'ABSTRACT ' + i, 'authors': ['A. Author'], 'venue': 'ICLR 2024 poster'}}
    if cdate: n['cdate'] = n['tcdate'] = ms(cdate)
    n.update({k: (ms(v) if isinstance(v, str) else v) for k, v in kw.items()})
    return n


OR_NOTES = [note('oldVisible1', 'Old relevant paper', tmdate='2024-01-10'), note('cdateAfter1', 'After T', cdate=F),
            note('tcdateDayT1', 'Imported on day T', tcdate=T.isoformat()), note('odateAfter1', 'Made public after T', odate=F),
            note('pdateAfter1', 'Published after T', pdate=F), note('mdateAfter1', 'Modified after T', mdate=F),
            note('forbidID01', 'Neutral title'), note('ftitle0001', FORBID_T), note('nodate0001', 'No date', cdate=None),
            note('lateRevise1', 'Revised after T (tmdate only)', tmdate=F), dict(note('dblpRecord1', 'Mirrored journal paper'), invitation='dblp.org/-/record')]


def or_reply(i, forum, kind, day, **kw):
    r = {'id': i, 'forum': forum, 'replyto': forum, 'invitation': f'ICLR.cc/2024/Conference/-/Paper1/{kind}', 'cdate': ms(day), 'tcdate': ms(day), 'tmdate': ms(day),
         'content': {'title': kind, 'review': 'TEXT ' + i, 'rating': '6'} if kind != 'Decision' else {'title': 'Paper decision', 'decision': 'Accept (Poster)'}}
    r.update({k: ms(v) for k, v in kw.items()})
    return r


def or_fetch(urls, replies):
    def fetch(url, headers=None):
        u = urllib.parse.unquote_plus(url); urls.append(u)
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        if q['source'][0] == 'reply': return json.dumps({'count': len(replies), 'notes': replies}).encode()
        v2 = 'api2.' in url                                              # v2 wraps fields in {"value": ...}
        ns = [dict(n, content={k: {'value': v} for k, v in n['content'].items()}, invitations=[n['invitation']]) if v2 else n for n in OR_NOTES]
        return json.dumps({'count': 10000, 'notes': ns}).encode()
    return fetch


class OpenReview(Base):
    def test_search_barrier(self):
        gw.fetch = or_fetch(self.urls, []); B = barrier()
        out, tot = gw.search_openreview('retrieval augmented generation', 20, B)
        self.assertEqual([o['id'] for o in out], ['openreview:oldVisible1', 'openreview:lateRevise1', 'openreview:dblpRecord1'])
        self.assertEqual((out[2]['type'], out[2]['venue'], out[2]['decision']), ('record', 'ICLR 2024 poster', None))   # a venue, not a decision
        self.assertEqual((out[0]['venue'], out[0]['decision'], out[0]['date']), ('ICLR 2024 poster', 'ICLR 2024 poster', '2024-03-14'))
        self.assertIsNone(out[1]['venue']); self.assertIsNone(out[1]['decision']); self.assertIn('masked', out[1]['content'])   # tmdate >= T: content masked
        self.assertGreaterEqual(B.excluded, 8)                                          # v1 and v2: every refused note counted
        self.assertIn('no provider-side date filter', tot)                               # the endpoint has none: said in the receipt
        self.assertEqual(len(self.urls), 2); self.assertTrue(any('api.openreview.net/notes/search' in u for u in self.urls))
        self.assertTrue(all('/notes/search?' in u for u in self.urls))                  # never /notes?id= (challenge)
        self.clean()

    def test_read_reviews_and_decision_after_T(self):
        reps = [or_reply('rev1', 'oldVisible1', 'Official_Review', '2024-01-05'),
                or_reply('rev2', 'oldVisible1', 'Official_Review', '2024-01-06', tmdate=F),     # edited after T: dropped
                or_reply('rev3', 'oldVisible1', 'Official_Review', T.isoformat()),             # created on day T: dropped
                or_reply('dec1', 'oldVisible1', 'Decision', F),                                # decision after T: never served
                or_reply('other', 'someOther1', 'Official_Review', '2024-01-05')]               # other forum: ignored
        gw.fetch = or_fetch(self.urls, reps); B = barrier()
        self.assertIn('search-openreview first', gw.read('openreview:oldVisible1', B)['refusal'])   # nothing met yet: no /notes?id= call
        gw.search_openreview('x', 20, B)
        r = gw.read('openreview:oldVisible1', B)
        self.assertEqual([x['id'] for x in r['reviews']], ['rev1']); self.assertEqual(r['replies_after_T_or_forbidden'], 3)
        self.assertIsNone(r['decision']); self.assertIsNone(r['venue']); self.assertIn('on/after T', r['decision_masked'])
        self.assertEqual(r['abstract'], 'ABSTRACT oldVisible1')
        self.assertNotIn('Accept', json.dumps(r))
        self.assertEqual(gw.read('openreview:lateRevise1', B)['abstract'], '(masked: note modified on/after T)')
        for i in ('cdateAfter1', 'tcdateDayT1', 'odateAfter1', 'pdateAfter1', 'mdateAfter1', 'forbidID01', 'ftitle0001'):
            self.assertIn('refusal', gw.read('openreview:' + i, B), i)
        self.assertIn('refusal', gw.read('openreview:../../x', B))
        self.clean()

    def test_read_decision_before_T(self):
        reps = [or_reply('rev1', 'oldVisible1', 'Official_Review', '2024-01-05'), or_reply('dec1', 'oldVisible1', 'Decision', '2024-01-20')]
        gw.fetch = or_fetch(self.urls, reps); B = barrier(); gw.search_openreview('x', 20, B)
        r = gw.read('openreview:oldVisible1', B)
        self.assertEqual((r['decision'], r['decision_date']), ('Accept (Poster)', '2024-01-20')); self.assertNotIn('decision_masked', r)

    def test_dates(self):
        self.assertEqual(gw.or_day(ms('2024-03-14', 23)), '2024-03-14'); self.assertIsNone(gw.or_day(None)); self.assertIsNone(gw.or_day('x'))
        self.assertTrue(re.match(gw.OR_PENDING, 'Submitted to ICLR 2024')); self.assertTrue(re.match(gw.OR_PENDING, 'ICLR 2024 Conference Submission'))
        self.assertFalse(re.match(gw.OR_PENDING, 'ICLR 2024 poster'))
        self.assertEqual(gw.INTERVAL['api2.openreview.net'], 2.0); self.assertIn(403, gw.STOP['api2.openreview.net'])


# ---------------------------------------------------------------- Zenodo

def zrec(i, title, created=V, pub=V, updated=None, doi=None, rel=None):
    h = {'id': i, 'doi': doi or f'10.5281/zenodo.{i}', 'links': {'self_html': f'https://zenodo.org/records/{i}'},
         'metadata': {'title': title, 'resource_type': {'type': 'dataset'}, 'creators': [{'name': 'Author, A.'}], 'description': '<p>DESC</p>',
                      'license': {'id': 'cc-by-4.0'}, 'related_identifiers': [{'relation': 'isSupplementTo', 'identifier': rel}] if rel else []}}
    if created: h['created'] = created + 'T09:00:00+00:00'
    if pub: h['metadata']['publication_date'] = pub
    h['updated'] = (updated or created or V) + 'T09:00:00+00:00'
    return h


Z_RECS = [zrec(1, 'Old dataset'), zrec(2, 'Created after T', created=F), zrec(3, 'Published on day T', pub=T.isoformat()),
          zrec(4, 'Partial publication date', pub=str(T.year)), zrec(5, 'Forbidden DOI', doi='10.1/forbid'),
          zrec(6, 'Supplement of the forbidden review', rel='10.1/forbid'), zrec(7, FORBID_T), zrec(8, 'No date', created=None, pub=None),
          zrec(9, 'Updated after T', updated=F)]


def z_fetch(urls):
    def fetch(url, headers=None):
        u = urllib.parse.unquote_plus(url); urls.append(u)
        m = re.search(r'/api/records/(\d+)$', url)
        if m:
            h = next((x for x in Z_RECS if str(x['id']) == m.group(1)), None)
            if not h: raise urllib.error.HTTPError(url, 404, 'not found', {}, None)
            return json.dumps(h).encode()
        return json.dumps({'hits': {'total': 9, 'hits': Z_RECS}}).encode()
    return fetch


class Zenodo(Base):
    def test_search_and_read(self):
        gw.fetch = z_fetch(self.urls); B = barrier()
        out, tot = gw.search_zenodo('graph dataset', 20, B)
        self.assertEqual([o['id'] for o in out], ['zenodo:1', 'zenodo:9']); self.assertEqual(B.excluded, 7)
        self.assertEqual((out[0]['date'], out[0]['date_deposited'], out[0]['type']), (V, V, 'dataset'))
        self.assertIn(f'(graph dataset) AND created:[{B.start} TO {B.eve}] AND publication_date:[{B.start} TO {B.eve}]', self.urls[0])
        self.assertIn('all_versions=true', self.urls[0])
        self.assertEqual(gw.read('zenodo:1', B)['abstract'], 'DESC')
        self.assertEqual(gw.read('zenodo:9', B)['abstract'], '(masked: metadata updated on/after T)')
        for i in range(2, 9): self.assertIn('refusal', gw.read(f'zenodo:{i}', B), i)
        self.assertEqual(gw.read('zenodo:404', B)['refusal'], 'not found'); self.assertIn('refusal', gw.read('zenodo:abc', B))
        self.clean()


# ---------------------------------------------------------------- HAL, computer science (hal-info) without breaking the law engine

def hal_fetch(urls):
    def doc(i, t, d, **kw):
        x = dict({'halId_s': f'hal-0000000{i}', 'title_s': [t], 'authFullName_s': ['A. Author'], 'docType_s': 'ART'}, **kw)
        if d: x.update(producedDate_s=d, submittedDate_s=d + ' 10:00:00' if len(d) == 10 else d)
        return x
    docs = [doc(0, 'Old relevant', V), doc(1, 'After T', F), doc(2, 'Day T', T.isoformat()), doc(3, 'Partial', str(T.year)),
            doc(4, 'Neutral', V, doiId_s='10.1/forbid'), doc(5, FORBID_T, V), doc(6, 'No date', None)]
    def fetch(url, headers=None):
        urls.append(urllib.parse.unquote_plus(url)); return json.dumps({'response': {'numFound': len(docs), 'docs': docs}}).encode()
    return fetch


class HalInfo(Base):
    def test_hal_info(self):
        gw.fetch = hal_fetch(self.urls); B = barrier()
        out, tot = gw.search_hal_info('graph neural network', 20, B)
        self.assertEqual([o['id'] for o in out], ['hal:hal-00000000']); self.assertEqual(out[0]['journal'], 'HAL'); self.assertEqual(B.excluded, 6)
        self.assertIn('fq=level0_domain_s:(info OR stat)', self.urls[0]); self.assertNotIn('shs.droit', self.urls[0])
        self.assertIn(f'producedDate_tdate:[{B.start}T00:00:00Z TO {B.eve}T23:59:59Z]', self.urls[0])
        self.assertIn(f'submittedDate_tdate:[{B.start}T00:00:00Z TO {B.eve}T23:59:59Z]', self.urls[0])
        gw.search_hal('données personnelles', 20, barrier())                     # the law engine keeps its law-only restriction
        self.assertIn('fq=level1_domain_s:shs.droit', self.urls[-1]); self.assertNotIn('level0_domain_s', self.urls[-1])
        self.clean()


# ---------------------------------------------------------------- code engine `usage` (ecosyste.ms)

PKG = {'purl': 'pkg:pypi/faiss-cpu', 'repository_url': 'https://github.com/facebookresearch/faiss', 'first_release_published_at': '2019-07-17T05:18:53.000Z',
       'latest_release_number': '9.9.9', 'latest_release_published_at': F + 'T10:00:00.000Z', 'versions_count': 30, 'dependent_packages_count': 352,
       'dependent_repos_count': 5592, 'docker_dependents_count': 254, 'downloads': 12177213, 'downloads_period': 'last-month', 'licenses': 'MIT',
       'maintainers': [{'login': 'facebook', 'role': 'Owner', 'created_at': F + 'T00:00:00Z'}]}
VERSIONS = [{'number': '9.9.9', 'published_at': F + 'T10:00:00.000Z'}, {'number': '9.9.8', 'published_at': T.isoformat() + 'T01:00:00.000Z'},
            {'number': '9.9.7', 'published_at': str(T.year)}, {'number': '9.9.6', 'published_at': None},
            {'number': '1.2.0', 'published_at': V + 'T08:00:00.000Z'}, {'number': '1.1.0', 'published_at': '2023-01-01T08:00:00.000Z'}]


class Usage(Base):
    def gateway(self, versions, pkg=PKG):
        sent = self.urls
        def send(client, url, headers):
            sent.append(urllib.parse.unquote(url)); self.assertNotIn('Authorization', headers)
            return 200, json.dumps(versions if '/versions?' in url else pkg).encode()
        self._send0 = sc.CodeClient._send; sc.CodeClient._send = send
        self.addCleanup(setattr, sc.CodeClient, '_send', self._send0)
        g = gw.Gateway([P.parent / 'plugins' / 'code.md'], T=T, run='t-usage', state=pathlib.Path(self.tmp.name) / 'state')
        g.client.sleep = lambda s: None; g.client.interval['default'] = 0
        return g

    def test_usage_barrier_and_as_of_now(self):
        g = self.gateway(VERSIONS)
        self.assertIn('ecosyste.ms', g.sources()['code_engines']); self.assertIn('usage', g.sources()['commands'])
        r = g.call('usage', 'pypi:faiss-cpu')
        x = r['results']
        self.assertEqual(x['latest_release_before_T'], {'number': '1.2.0', 'date': V + 'T08:00:00.000Z'})
        self.assertEqual((x['as_of'], x['dependent_repos_count'], x['first_release_date']), ('now', 5592, '2019-07-17T05:18:53.000Z'))
        self.assertIn('not as of T', x['as_of_note']); self.assertIn('as_of', r['warning'])
        dump = json.dumps(x)
        for late in ('9.9.9', '9.9.8', '9.9.7', F): self.assertNotIn(late, dump)              # no dated field on/after T, no current latest release
        self.assertEqual(x['maintainers'], [{'login': 'facebook', 'role': 'Owner'}])
        self.assertTrue(any(f'published_before={T}' in u for u in self.urls))               # provider-side bound
        self.assertEqual(r['excluded_post_T_or_forbidden'], 4)
        self.clean()

    def test_usage_refusals(self):
        g = self.gateway([{'number': '2.0.0', 'published_at': F + 'T10:00:00Z'}], dict(PKG, first_release_published_at=F + 'T10:00:00Z'))
        self.assertIn('no release published before T', g.call('usage', 'npm:@scope/pkg')['results']['refusal'])
        for bad in ('pypi', 'foo:bar', 'pypi:../etc', 'pypi:a b'): self.assertIn('refusal', g.call('usage', bad)['results'], bad)
        self.assertTrue(re.fullmatch(sc.USAGE_FORM, 'maven:org.apache.commons:commons-lang3'))
        h = gw.Gateway([P.parent / 'plugins' / 'cs-ai.md'], T=T, run='t-u2', state=pathlib.Path(self.tmp.name) / 's2')
        self.assertIn('not declared', h.call('usage', 'pypi:faiss-cpu')['refusal'])        # never served without its plugin


# ---------------------------------------------------------------- cs-ai: paper-code declared, same barrier as the code plugin

class CsAiPaperCode(Base):
    def test_paper_code_in_cs_ai(self):
        g = gw.Gateway([P.parent / 'plugins' / 'cs-ai.md'], T=T, run='t-pc', state=pathlib.Path(self.tmp.name) / 'state')
        s = g.sources()
        self.assertEqual(s['code_engines'], ['paper-code']); self.assertIn('paper-code', s['commands'])
        self.assertTrue({'openreview', 'zenodo', 'hal-info'} <= set(s['engines'])); self.assertNotIn('hal', s['engines'])   # law hal not pulled into cs-ai
        def send(client, url, headers):
            if '/api/papers/' in url: return 200, json.dumps({'publishedAt': V + 'T00:00:00Z', 'githubRepo': 'https://github.com/a/b', 'githubStars': 3}).encode()
            return 200, json.dumps([{'id': 'm/old', 'lastModified': V + 'T00:00:00Z'}, {'id': 'm/late', 'lastModified': F + 'T00:00:00Z'},
                                    {'id': 'm/dayT', 'lastModified': T.isoformat() + 'T00:00:00Z'}]).encode()
        send0 = sc.CodeClient._send; sc.CodeClient._send = send; self.addCleanup(setattr, sc.CodeClient, '_send', send0)
        g.client.sleep = lambda s: None
        x = g.call('paper-code', 'arxiv:2401.00001')['results']
        self.assertEqual([m['id'] for m in x['models']], ['m/old']); self.assertEqual(len(x['repos']), 1)
        def late(client, url, headers): return 200, json.dumps({'publishedAt': F + 'T00:00:00Z'} if '/api/papers/' in url else []).encode()
        sc.CodeClient._send = late
        g2 = gw.Gateway([P.parent / 'plugins' / 'cs-ai.md'], T=T, run='t-pc2', state=pathlib.Path(self.tmp.name) / 'state2'); g2.client.sleep = lambda s: None
        self.assertEqual(g2.call('paper-code', 'arxiv:2401.00002')['results'], {'refusal': 'after T'})


# ---------------------------------------------------------------- Stack Exchange: tos_forbidden, not wired; check_keys display

class NotWiredAndDisplay(unittest.TestCase):
    def test_stackexchange_not_wired(self):
        code = gw.read_plugin(P.parent / 'plugins' / 'code.md')
        self.assertNotIn('stackexchange', code['engines'] + code['code_engines'])
        self.assertNotIn('stackexchange', set(gw.ENGINES) | set(gw.CODE_ENGINES.values()))
        self.assertIn('stackexchange=tos_forbidden', (P.parent / 'plugins' / 'code.md').read_text(encoding='utf-8'))

    def test_check_keys_served_by(self):
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            (d / 'with.md').write_text('# P\n## Sources\n```sources\nengines: github, hf-papers, pypi, code, paper-code, codeberg\nkeys: VP_GITHUB_TOKEN\n```\n', encoding='utf-8')
            (d / 'without.md').write_text('# P\n## Sources\n```sources\nengines: github, hf-papers, openalex\nkeys: OPENALEX_KEY\n```\n', encoding='utf-8')
            home = os.environ.get('HOME'); os.environ['HOME'] = str(d)
            try: rep = ck.report([d / 'with.md', d / 'without.md'])
            finally:
                if home is None: os.environ.pop('HOME', None)
                else: os.environ['HOME'] = home
        w, wo = rep['plugins']
        self.assertEqual(w['not_wired'], ['pypi', 'codeberg']); self.assertEqual(w['served_by'], {'github': 'code', 'hf-papers': 'paper-code'})
        self.assertNotIn('pypi', w['served_by'])          # versions not declared: pypi is not served
        self.assertEqual(wo['not_wired'], ['github', 'hf-papers']); self.assertEqual(wo['served_by'], {})   # serving engine not declared
        t = ck.text(rep)
        self.assertIn('served by      : github (via code), hf-papers (via paper-code)', t); self.assertIn('not wired      : pypi, codeberg', t)
        real = ck.report([P.parent / 'plugins' / 'code.md'])['plugins'][0]
        for m in ('github', 'sourcegraph', 'deps.dev', 'hf-papers', 'pypi', 'npm', 'crates', 'software-heritage'): self.assertNotIn(m, real['not_wired'], m)
        self.assertIn('ecosyste.ms', real['active'])


if __name__ == '__main__':
    unittest.main()
