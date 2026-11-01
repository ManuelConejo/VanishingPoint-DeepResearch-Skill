#!/usr/bin/env python3
"""Offline tests of the wayback source (Internet Archive CDX + Memento, level 1): last capture before T served raw (id_), several captures
(the latest before T wins), none before T -> explicit not_found, 429 / 503 -> honest rate_limited with Retry-After and no further request,
URL with a query string (encoded once), capture on/after T refused locally even if the provider returns it, non-text capture, bad URL,
declaration (access api, pacing, stop codes). Transport replaced (gateway.fetch). Run: python3 -I tests/test_wayback.py"""
import email.message, json, os, pathlib, sys, tempfile, unittest, urllib.error, urllib.parse
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools')); import gateway as gw, sources as reg   # noqa: E702

T = '2024-06-15'; URL = 'https://example.org/page'
HEAD = ['timestamp', 'original', 'mimetype', 'statuscode', 'digest']
HTML = b'<html><head><style>p{}</style><script>var x=1;</script></head><body><h1>Hello</h1><p>Archived  text</p></body></html>'


def cdx(*rows): return json.dumps([HEAD] + [list(r) for r in rows]).encode()


class Wayback(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = pathlib.Path(self.tmp.name)
        self.saved = (gw.fetch, gw.STATE); gw.STATE = self.d / 'state'; self.urls = []; self.cdx = cdx(); self.fail = None; self.body = HTML
        os.environ['HOME'] = str(self.d / 'home'); gw.fetch = self.fake
        q = self.d / 'p.md'; q.write_text('```sources\nengines: wayback\n```\n', encoding='utf-8'); self.plugin = str(q)

    def tearDown(self): gw.fetch, gw.STATE = self.saved; self.tmp.cleanup()

    def fake(self, url, headers=None):
        self.urls.append(url)
        if self.fail:
            h = email.message.Message()
            if self.fail[1]: h['Retry-After'] = self.fail[1]
            raise urllib.error.HTTPError(url, self.fail[0], 'x', h, None)
        return self.cdx if '/cdx/search/cdx' in url else self.body

    def g(self, name='st'): return gw.Gateway([self.plugin], T=T, state=str(self.d / name))

    def test_capture_before_T_served_raw(self):
        self.cdx = cdx(('20240301120000', URL, 'text/html', '200', 'AAA'))
        r = self.g().read('wayback:' + URL)['results']
        self.assertEqual(r['captured'], '20240301120000'); self.assertEqual(r['date'], '2024-03-01'); self.assertIn('captured before T', r['captured_before_T'])
        self.assertIn('not its publication date', r['captured_before_T']); self.assertIn('Hello Archived text', r['text']); self.assertNotIn('var x', r['text'])
        self.assertEqual(r['archive_url'], 'https://web.archive.org/web/20240301120000id_/' + URL)
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.urls[0]).query)
        self.assertEqual((q['to'], q['limit'], q['output'], q['filter']), (['20240614235959'], ['-1'], ['json'], ['statuscode:200']))   # eve of T, last row
        self.assertEqual(self.urls[1], 'https://web.archive.org/web/20240301120000id_/' + URL)

    def test_several_captures_latest_before_T(self):
        self.cdx = cdx(('20230101000000', URL, 'text/html', '200', 'A'), ('20240614235959', URL, 'text/html', '200', 'B'),
                       ('20240615000000', URL, 'text/html', '200', 'C'), ('20250101000000', URL, 'text/html', '200', 'D'))   # provider ignores `to`
        r = self.g().read('wayback:' + URL)['results']
        self.assertEqual(r['captured'], '20240614235959')                              # the capture on day T is refused locally
        s = self.g('st2').search('wayback', URL)['results']; self.assertEqual([x['captured'] for x in s], ['20240614235959']); self.assertNotIn('text', s[0])

    def test_none_before_T_is_not_found(self):
        self.cdx = cdx()
        self.assertEqual(self.g().read('wayback:' + URL)['results']['status'], 'not_found')
        self.cdx = cdx(('20240615000001', URL, 'text/html', '200', 'C'))
        r = self.g('st2').read('wayback:' + URL)['results']; self.assertEqual(r['status'], 'not_found'); self.assertIn('not_found', r['refusal'])
        self.assertEqual(len(self.urls), 2)                                           # no playback request

    def test_rate_limited_honest_and_respects_retry_after(self):
        g = self.g(); self.fail = (429, '120')
        r = g.read('wayback:' + URL)['results']; self.assertEqual(r['status'], 'rate_limited'); self.assertTrue(110 <= r['retry_after_s'] <= 125)
        n = len(self.urls); self.fail = None; self.cdx = cdx(('20240301120000', URL, 'text/html', '200', 'A'))
        r2 = g.read('wayback:' + URL)['results']; self.assertEqual(r2['status'], 'rate_limited'); self.assertEqual(len(self.urls), n)   # no request while limited
        self.fail = (503, None); r3 = self.g('st3').search('wayback', URL)['results']; self.assertEqual(r3, [])
        self.fail = (503, None); r4 = self.g('st4').read('wayback:' + URL)['results']; self.assertEqual(r4['status'], 'rate_limited')
        self.fail = (500, None)
        self.assertIn('error', self.g('st5').read('wayback:' + URL)['results'])      # another error is typed, not hidden as empty

    def test_query_string_url(self):
        u = 'https://example.org/a b?x=1&y=2#frag'.replace(' ', '%20').split('#')[0]
        self.cdx = cdx(('20240301120000', u, 'text/html', '200', 'A'))
        r = self.g().read('wayback:' + u)['results']; self.assertEqual(r['captured'], '20240301120000')
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.urls[0]).query)
        self.assertEqual(q['url'], [u]); self.assertEqual(self.urls[1], 'https://web.archive.org/web/20240301120000id_/' + u)

    def test_non_text_and_bad_input_and_forbidden(self):
        self.cdx = cdx(('20240301120000', URL, 'application/pdf', '200', 'A'))
        r = self.g().read('wayback:' + URL)['results']; self.assertIsNone(r['text']); self.assertEqual(len(self.urls), 1)
        self.assertIn('refusal', self.g('s2').read('wayback:not a url')['results']); self.assertIn('refusal', self.g('s3').read('wayback:https://u:p@example.org/')['results'])
        g = self.g('s4'); g.B.forbidden |= gw.id_forms('wayback:' + URL) if hasattr(gw, 'id_forms') else {'wayback:' + URL}   # forbidden list = same as the DOIs
        self.cdx = cdx(('20240301120000', URL, 'text/html', '200', 'A')); self.assertEqual(g.read('wayback:' + URL)['results']['status'], 'not_found')

    def test_declaration(self):
        s = next(x for x in reg.SOURCES if x['name'] == 'wayback')
        self.assertEqual(s['access'], 'api'); self.assertEqual(list(s['hosts']), ['web.archive.org']); self.assertGreaterEqual(s['hosts']['web.archive.org']['interval'], 1.0)
        self.assertTrue({429, 503} <= set(s['hosts']['web.archive.org']['stop'])); self.assertIs(reg.owner('wayback:' + URL), s); self.assertIn('wayback', gw.ENGINES)
        for p in (P.parent / 'plugins').glob('*.md'):                                   # not declared in any plugin (the plugins change by duel)
            m = __import__('re').search(r'```sources[^\n]*\n(.*?)```', p.read_text(encoding='utf-8'), __import__('re').S)
            self.assertNotIn('wayback', m.group(1) if m else '')


if __name__ == '__main__':
    unittest.main()
