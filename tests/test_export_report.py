#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of export_report.py: a fixture report (eight sections, a table, a list, [n] -> anchors and back-links) becomes one
self-contained HTML page; hostile text (<script>, "><img onerror>, javascript: link, raw HTML) comes out escaped or neutralised; the
header takes card/run/verdicts fields when present and is absent otherwise; --pdf without any converter (empty PATH, module blocked)
keeps the HTML, exits 0 and says so; with a converter present in the test environment, a real PDF starting with %PDF."""
import contextlib, io, json, os, pathlib, re, sys, tempfile, unittest
from unittest import mock
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools')); import export_report as E   # noqa: E702

REPORT = """*Example run, fixture.*

# Does M beat N on X?

## Executive Summary

M reaches **71.2 %** on X [1], while N stays at *64 %* [2][3]. See also [4, 1]. A bracket that is not a citation: [9].
Evil: <script>alert(1)</script> and "><img src=x onerror=alert(2)> and [click](javascript:alert(3)) and ![pic](http://e.x/p.png).
A safe [link](https://example.org/a?b=1&c=2) and a bare https://example.org/z. and `code <b>` stays code.

## Introduction

T = 2026-10-26.

- first item [1]
- second item with `x|y`
  continued line

1. one
2. two

> A quoted line [2].

## Main Analysis

### Finding 1 — M is better

| Model | X score | Note |
|:------|-------:|------|
| M | 71.2 | [1] |
| N | 64.0 | <i>bad</i> \\| pipe |

Verdict: established.

### Finding 2 — N is close

Under_score_words stay as is; _italic_ works. Verdict: probable [3].

## Synthesis & Insights

Together [1] [2].

## Limitations & Caveats

Few sources.

## Recommendations

Search more.

## Bibliography

[1] A. Author. Paper A. 2022. doi:10.1000/abc.123. Basis: abstract.
[2] B. Author. Paper B. 2021. pmid:123456. Basis: abstract.
[3] C. Author. Paper C. 2020. arxiv:2001.01234. Basis: title.

[4] D. Author, <script>x()</script>, https://example.org/d.

## Methodology Appendix

Verification: `[1]` / A1 corrected. Mode: standard.
"""
CARD = {'card_id': 'C1', 'question': 'Does M beat N <b>on</b> X?', 'claims': []}
RUN = {'run': ['fixture'], 'T': ['2026-10-26'], 'calls': 12, 'plugins': ['cs-ai']}
VERDICTS = {'claims': [{'id': 'A1', 'status': 'FOUND'}, {'id': 'A2', 'status': 'FOUND'}, {'id': 'A3', 'status': 'DISTORTED'}]}


def run_dir(tmp, **files):
    d = pathlib.Path(tmp) / 'run'; d.mkdir()
    (d / 'REPORT.md').write_text(REPORT, encoding='utf-8')
    for name, obj in files.items(): (d / name.replace('_', '.')).write_text(json.dumps(obj), encoding='utf-8')
    return d


def call(argv, path='', block=True):
    out = io.StringIO()
    with mock.patch.dict(os.environ, {'PATH': path}), mock.patch.dict(sys.modules, {'weasyprint': None} if block else {}), contextlib.redirect_stdout(out):
        rc = E.main(argv)
    return rc, out.getvalue()


class Export(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)

    def html(self, **files):
        d = run_dir(self.tmp.name, **files); rc, out = call([str(d)])
        self.assertEqual(rc, 0); self.assertIn('REPORT.html', out)
        return d, (d / 'REPORT.html').read_text(encoding='utf-8')

    def test_structure_and_citations(self):
        d, h = self.html()
        self.assertTrue(h.startswith('<!DOCTYPE html>')); self.assertIn('<title>Does M beat N on X?</title>', h)
        for s in ('Executive Summary', 'Introduction', 'Main Analysis', 'Synthesis &amp; Insights', 'Limitations &amp; Caveats',
                  'Recommendations', 'Bibliography', 'Methodology Appendix'):
            self.assertRegex(h, r'<h2 id="[\w-]+"[^>]*>' + re.escape(s) + '</h2>')
        self.assertIn('<h2 id="bibliography" class="pb">', h); self.assertIn('<h2 id="methodology-appendix" class="pb">', h)
        self.assertIn('<h3 id="finding-1">Finding 1 — M is better</h3>', h)
        self.assertIn('<a class="cite" id="cite-1-1" href="#ref-1">[1]</a>', h)
        self.assertIn('href="#ref-2">[2]</a><a class="cite" id="cite-3-1" href="#ref-3">[3]</a>', h)
        self.assertIn('id="cite-4-1" href="#ref-4">[4]</a>', h)                   # [4, 1]: both linked
        self.assertIn('[9]', h); self.assertNotIn('#ref-9', h)                     # no entry -> left as text
        for n in (1, 2, 3, 4): self.assertIn(f'<p id="ref-{n}"><span class="n">[{n}]</span>', h)
        self.assertIn('<a href="#cite-1-1" title="back to citation">', h)
        self.assertIn('<a href="https://doi.org/10.1000/abc.123">doi:10.1000/abc.123</a>. Basis', h)
        self.assertIn('<a href="https://pubmed.ncbi.nlm.nih.gov/123456/">pmid:123456</a>', h)
        self.assertIn('<a href="https://arxiv.org/abs/2001.01234">arxiv:2001.01234</a>', h)
        self.assertIn('<code>[1]</code> / A1', h)                                   # code span untouched
        # table, alignment, escaped pipe, lists, quote, emphasis
        self.assertIn('<table><thead><tr><th style="text-align:left">Model</th><th style="text-align:right">X score</th><th>Note</th></tr></thead>', h)
        self.assertIn('<td>&lt;i&gt;bad&lt;/i&gt; | pipe</td>', h)
        self.assertIn('<li>second item with <code>x|y</code> continued line</li>', h); self.assertIn('<ol><li>one</li><li>two</li></ol>', h)
        self.assertRegex(h, r'<blockquote><p>A quoted line <a class="cite"[^>]*>\[2\]</a>\.</p></blockquote>')
        self.assertIn('<strong>71.2 %</strong>', h); self.assertIn('<em>64 %</em>', h); self.assertIn('<em>italic</em>', h)
        self.assertIn('Under_score_words', h)
        self.assertIn('<a href="https://example.org/a?b=1&amp;c=2">link</a>', h); self.assertIn('<a href="https://example.org/z">https://example.org/z</a>.', h)
        self.assertIn('<nav id="contents">', h); self.assertIn('<a href="#finding-2">', h)
        self.assertIn('@page{size:A4', h); self.assertIn('tr{break-inside:avoid', h)

    def test_hostile_text_is_neutralised(self):
        d, h = self.html()
        self.assertNotIn('<script', h.lower()); self.assertNotIn('<img', h.lower()); self.assertNotIn('<i>', h)
        self.assertNotIn('javascript:', re.sub(r'&[^;]+;', '', ''.join(re.findall(r'href="([^"]*)"', h))).lower())
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', h)
        self.assertIn('&quot;&gt;&lt;img src=x onerror=alert(2)&gt;', h)
        self.assertIn('and click and', h)                                           # javascript: link -> its text only
        self.assertIn('and pic.', h); self.assertNotIn('e.x/p.png', h)             # image -> alt text, never fetched
        self.assertIn('<code>code &lt;b&gt;</code>', h)
        self.assertNotRegex(h, r'<[a-z]+[^>]*\son\w+=')                             # no event handler attribute anywhere
        self.assertNotRegex(h, r'<[a-z]+[^>]*\ssrc=')                              # no src attribute: nothing external to load

    def test_header_present_and_absent(self):
        _, h = self.html(card_json=CARD, run_json=RUN, verdicts_json=VERDICTS)
        meta = re.search(r'<div class="meta">(.*?)</div>', h).group(1)
        self.assertIn('<dt>Question</dt><dd>Does M beat N &lt;b&gt;on&lt;/b&gt; X?</dd>', meta)
        self.assertIn('<dt>Date T</dt><dd>2026-10-26</dd>', meta); self.assertIn('<dt>Plugin(s)</dt><dd>cs-ai</dd>', meta)
        self.assertIn('<dt>Mode</dt><dd>standard</dd>', meta)                    # from the appendix
        self.assertIn('<dt>Verification</dt><dd>3 claims checked: FOUND 2, DISTORTED 1</dd>', meta)
        self.assertIn('<dt>Gateway calls</dt><dd>12</dd>', meta); self.assertIn('<dt>Run</dt><dd>fixture</dd>', meta)
        d = run_dir(tempfile.mkdtemp(dir=self.tmp.name)); (d / 'REPORT.md').write_text(REPORT.replace(' Mode: standard.', ''), encoding='utf-8')
        self.assertEqual(E.meta(d), [])
        rc, _ = call([str(d)]); h = (d / 'REPORT.html').read_text(encoding='utf-8')
        self.assertNotIn('class="meta"', h); self.assertIn('<nav id="contents">', h)
        (d / 'card.json').write_text('{broken', encoding='utf-8'); self.assertEqual(E.meta(d), [])   # unreadable JSON: ignored

    def test_pdf_without_converter(self):
        d = run_dir(self.tmp.name); out = pathlib.Path(self.tmp.name) / 'out'
        with tempfile.TemporaryDirectory() as empty:
            rc, msg = call([str(d), '--pdf', '--out', str(out)], path=empty)
        self.assertEqual(rc, 0); self.assertTrue((out / 'REPORT.html').is_file()); self.assertFalse((out / 'REPORT.pdf').exists())
        self.assertEqual(msg.splitlines()[-1], 'PDF: no converter found (WeasyPrint, Chromium/Chrome, wkhtmltopdf, pandoc); REPORT.html prints to PDF from any browser.')
        self.assertEqual(len(msg.splitlines()), 2)

    def test_missing_report(self):
        with contextlib.redirect_stderr(io.StringIO()): self.assertEqual(E.main([self.tmp.name]), 2)

    def test_real_pdf_if_a_converter_exists(self):
        with mock.patch.dict(os.environ, {'PATH': os.environ.get('PATH', '/usr/bin:/bin')}):
            if not E.converters(): self.skipTest('no PDF converter in this environment')
        d = run_dir(self.tmp.name); rc, msg = call([str(d), '--pdf'], path=os.environ.get('PATH', '/usr/bin:/bin'), block=False)
        self.assertEqual(rc, 0); pdf = d / 'REPORT.pdf'
        if not pdf.exists(): self.skipTest('converter present but failed here: ' + msg.splitlines()[-1])
        self.assertEqual(pdf.read_bytes()[:4], b'%PDF')


if __name__ == '__main__':
    unittest.main()
