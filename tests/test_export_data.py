#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of export_data.py: a fixture run (seven bibliography entries of every kind, a study whose criteria start with = - @ +,
claims with verdicts) gives studies.csv (columns, rows, RFC 4180 quoting, formula injection neutralised, statuses counted) and
references.bib (balanced braces, unique keys, & % _ escaped), .ris (TY ... ER records, well-formed tags), .json (CSL-JSON with id, type,
title); fields absent from the run stay absent; on a fixture trimmed from a real run, as many references as bibliography entries."""
import contextlib, csv, io, json, os, pathlib, re, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools')); import export_data as X   # noqa: E702

REPORT = """# Q

## Executive Summary

A [1] B [2] C [3] D [4] E [5] F [6] G [7].

## Bibliography

[1] Massé et al. Vitamin D, calcium, or both for fractures (meta-analysis), BMJ. 2026. pmid:42161415. Basis: abstract.
[2] Badalova F., Smith J. "Tools & costs: 50% of_citations", 2025, arxiv:2507.01234, basis abstract.
[3] Some Paper With No Author Or Year. doi:10.1000/x_y%z.
[4] ClinicalTrials.gov. Vitamin D trial. 2019. nct:NCT01234567. Basis: title.
[5] Regulation (EU) 2016/679 (GDPR). 2016. celex:32016R0679. Basis: abstract.
[6] owner/repo, `src/main_loop.py:12@0123abcd` (l.12 loop) — https://github.com/owner/repo/blob/0123abcd/src/main_loop.py#L12
[7] VITAL investigators. Vitamin D and falls, J Clin Endocrinol Metab. 2020. pmid:32492153. Basis: abstract.

## Methodology Appendix

Done.
"""
CARD = {'card_id': 'fx', 'question': 'Q', 'sources': {'S1': {'pmid': '42161415', 'title': 'Vitamin D, calcium, or both for fractures (meta-analysis)'},
        'S3': {'doi': '10.1000/x_y%z', 'title': 'Some Paper With No Author Or Year'}, 'S7': {'pmid': '32492153', 'title': 'Vitamin D and falls'}},
        'claims': [{'id': 'A1', 'text': 't', 'source': {'key': 'S1'}}, {'id': 'A2', 'text': 't', 'source': {'key': 'S1'}},
                   {'id': 'A3', 'text': 't', 'source': {'key': 'S1'}}, {'id': 'A4', 'text': 't', 'source': {'key': 'S1'}},
                   {'id': 'A5', 'text': 't', 'source': {'key': 'S7'}}]}
VERDICTS = {'claims': [{'id': 'A1', 'status': 'FOUND'}, {'id': 'A2', 'status': 'FOUND'}, {'id': 'A3', 'status': 'DISTORTED'}, {'id': 'A5', 'status': 'UNVERIFIED'}]}
CRIT = {'population': '=HYPERLINK("http://e.x")', 'intervention_exposure': '-5 mg', 'comparator': '@x', 'results': 'RR 0.91, "high", certainty\nline 2',
        'study_design': '+meta', 'date_language_type': '2026, English.'}
RESULT = {'studies': [{'id': 'pmid:42161415', 'title': 'Vitamin D, calcium, or both for fractures (meta-analysis)', 'year': '2026', 'confidence': 0.9,
                       'criteria': CRIT, 'basis': 'abstract'},
                      {'id': 'pmid:32492153', 'title': 'Vitamin D and falls', 'year': '2020', 'confidence': 0.8,
                       'criteria': {**{k: 'ok' for k in CRIT}, 'extra_field': 'more'}, 'basis': 'title'}], 'saturation': 's', 'calls_used': 3}


def run_dir(tmp, report=REPORT, **files):
    d = pathlib.Path(tmp) / 'run'; d.mkdir()
    (d / 'REPORT.md').write_text(report, encoding='utf-8')
    for name, obj in files.items(): (d / f'{name}.json').write_text(json.dumps(obj), encoding='utf-8')
    return d


def call(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()): rc = X.main(argv)
    return rc, out.getvalue()


def bib_records(text):
    """Minimal BibTeX reader: [(type, key, {field: value})], fails on unbalanced braces."""
    recs, i = [], 0
    while (m := re.compile(r'@(\w+)\{([^,\s]+),').search(text, i)):
        depth, j = 1, m.end()
        while depth:
            c = text[j]
            if c == '\\': j += 2; continue
            depth += (c == '{') - (c == '}'); j += 1
        body = text[m.end():j - 1]; fields = {}
        for f in re.finditer(r'^\s*(\w+) = \{(.*)\},?$', body, re.M): fields[f.group(1)] = f.group(2)
        recs.append((m.group(1), m.group(2), fields)); i = j
    return recs


class Export(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.d = run_dir(self.tmp.name, card=CARD, result=RESULT, verdicts=VERDICTS)
        rc, self.out = call([str(self.d)]); self.assertEqual(rc, 0)
        self.f = {n: (self.d / n).read_bytes() for n in ('studies.csv', 'references.bib', 'references.ris', 'references.json')}

    def test_paths_printed(self):
        for n in self.f: self.assertIn(str((self.d / n).resolve()), self.out)
        self.assertIn('2 studies, 7 references', self.out)

    def test_csv(self):
        raw = self.f['studies.csv']; self.assertFalse(raw.startswith(b'\xef\xbb\xbf')); self.assertIn(b'\r\n', raw)
        rows = list(csv.reader(io.StringIO(raw.decode('utf-8'), newline='')))
        self.assertEqual(rows[0], ['id', 'title', 'year', 'population', 'intervention_exposure', 'comparator', 'results', 'study_design',
                                   'date_language_type', 'extra_field', 'confidence', 'basis', 'claims', 'found', 'distorted', 'absent', 'invalid',
                                   'source_unavailable', 'unverified', 'no_verdict', 'ref'])
        self.assertEqual(len(rows), 3); h = rows[0]; r1, r2 = (dict(zip(h, r)) for r in rows[1:])
        self.assertEqual(r1['population'], '\'=HYPERLINK("http://e.x")'); self.assertEqual(r1['intervention_exposure'], "'-5 mg")
        self.assertEqual(r1['comparator'], "'@x"); self.assertEqual(r1['study_design'], "'+meta")
        self.assertEqual(r1['results'], 'RR 0.91, "high", certainty\nline 2')       # quotes, comma, newline round-trip
        self.assertIn(b'"RR 0.91, ""high"", certainty\nline 2"', raw)
        self.assertEqual(r1['title'], 'Vitamin D, calcium, or both for fractures (meta-analysis)'); self.assertEqual(r1['year'], '2026')
        self.assertEqual((r1['claims'], r1['found'], r1['distorted'], r1['no_verdict'], r1['ref']), ('4', '2', '1', '1', '1'))
        self.assertEqual((r2['claims'], r2['unverified'], r2['found'], r2['ref'], r2['extra_field'], r2['basis']), ('1', '1', '0', '7', 'more', 'title'))
        self.assertEqual(r1['extra_field'], '')

    def test_bibtex(self):
        t = self.f['references.bib'].decode('utf-8'); self.assertEqual(t.count('{'), t.count('}') + t.count('\\{') - t.count('\\}'))
        recs = bib_records(t); self.assertEqual(len(recs), 7)
        keys = [k for _, k, _ in recs]; self.assertEqual(len(set(keys)), 7); self.assertTrue(all(re.fullmatch(r'[a-z0-9]+', k) for k in keys))
        self.assertEqual(keys[0], 'masse2026vitamin'); self.assertEqual(keys, [k for _, k, _ in bib_records(X.bibtex(X.entries(self.d)))])  # stable
        by = {f['note'].split('report [')[1][:-1]: (ty, f) for ty, _, f in recs}
        for ty, f in by.values():
            for k, v in f.items():
                if k not in ('url', 'doi'): self.assertIsNone(re.search(r'(?<!\\)[&%_#$]', v), (k, v))
        ty, f = by['2']; self.assertEqual(ty, 'misc'); self.assertEqual(f['title'], r'{Tools \& costs: 50\% of\_citations}')
        self.assertEqual(f['author'], 'Badalova, F. and Smith, J.'); self.assertEqual(f['eprint'], '2507.01234'); self.assertEqual(f['year'], '2025')
        ty, f = by['1']; self.assertEqual(ty, 'article'); self.assertEqual(f['journal'], 'BMJ'); self.assertEqual(f['author'], 'Massé and others')
        self.assertIn('VP id: pmid:42161415', f['note']); self.assertEqual(f['url'], 'https://pubmed.ncbi.nlm.nih.gov/42161415/')
        ty, f = by['3']; self.assertEqual(f['doi'], '10.1000/x_y%z'); self.assertNotIn('author', f); self.assertNotIn('year', f)
        self.assertNotIn('journal', f); self.assertEqual(f['title'], '{Some Paper With No Author Or Year}')
        self.assertEqual(by['7'][1]['author'], '{VITAL investigators}'); self.assertEqual(by['7'][1]['journal'], 'J Clin Endocrinol Metab')
        self.assertEqual(by['6'][1]['version'], '0123abcd'); self.assertEqual(by['6'][1]['title'], r'{src/main\_loop.py}')
        self.assertEqual(by['6'][1]['url'], 'https://github.com/owner/repo/blob/0123abcd/src/main_loop.py#L12')

    def test_ris(self):
        t = self.f['references.ris'].decode('utf-8'); lines = t.split('\r\n')
        recs, cur = [], None
        for l in lines:
            if not l: continue
            self.assertRegex(l, r'^[A-Z][A-Z0-9]  - ')
            if l.startswith('TY  - '): self.assertIsNone(cur); cur = [l]
            elif l.startswith('ER  - '): recs.append(cur); cur = None
            else: self.assertIsNotNone(cur); cur.append(l)
        self.assertIsNone(cur); self.assertEqual(len(recs), 7)
        self.assertEqual([r[0][6:] for r in recs], ['JOUR', 'UNPB', 'JOUR', 'GEN', 'LEGAL', 'COMP', 'JOUR'])
        self.assertIn('AU  - Badalova, F.', recs[1]); self.assertIn('TI  - Tools & costs: 50% of_citations', recs[1])
        self.assertFalse(any(l.startswith(('AU', 'PY', 'JO')) for l in recs[2]))
        self.assertIn('AN  - nct:NCT01234567', recs[3]); self.assertIn('AN  - celex:32016R0679', recs[4]); self.assertIn('PB  - owner/repo', recs[5])

    def test_csl(self):
        data = json.loads(self.f['references.json']); self.assertEqual(len(data), 7)
        for c in data:
            self.assertTrue(c['id'] and c['type'] and c['title']); self.assertIn('VP id:', c['note'])
        self.assertEqual([c['type'] for c in data], ['article-journal', 'article', 'article-journal', 'document', 'legislation', 'software', 'article-journal'])
        self.assertEqual(data[0]['issued'], {'date-parts': [[2026]]}); self.assertEqual(data[0]['container-title'], 'BMJ'); self.assertEqual(data[0]['PMID'], '42161415')
        self.assertEqual(data[1]['author'], [{'family': 'Badalova', 'given': 'F.'}, {'family': 'Smith', 'given': 'J.'}])
        self.assertEqual(data[6]['author'], [{'literal': 'VITAL investigators'}])
        for k in ('author', 'issued', 'container-title'): self.assertNotIn(k, data[2])
        self.assertEqual(data[2]['DOI'], '10.1000/x_y%z')

    def test_report_only_and_missing(self):
        d = pathlib.Path(tempfile.mkdtemp(dir=self.tmp.name)); (d / 'REPORT.md').write_text(REPORT, encoding='utf-8'); out = d / 'o'
        rc, msg = call([str(d), '--out', str(out)]); self.assertEqual(rc, 0); self.assertIn('0 studies, 7 references', msg)
        self.assertEqual((out / 'studies.csv').read_text(encoding='utf-8').count('\n'), 1)
        self.assertEqual(json.loads((out / 'references.json').read_text(encoding='utf-8'))[0]['title'], 'Vitamin D, calcium, or both for fractures (meta-analysis), BMJ')
        self.assertEqual(call([str(pathlib.Path(self.tmp.name) / 'none')])[0], 2)

    def test_trimmed_real_run(self):
        """fixtures/export_run: four entries trimmed from a real biology run (with numbering gaps), its card/result/verdicts."""
        d = P / 'fixtures' / 'export_run'; out = pathlib.Path(self.tmp.name) / 'bio'
        rc, msg = call([str(d), '--out', str(out)]); self.assertEqual(rc, 0); self.assertIn('4 studies, 4 references', msg)
        n = len(X.bib_entries((d / 'REPORT.md').read_text(encoding='utf-8'))); self.assertEqual(n, 4)
        data = json.loads((out / 'references.json').read_text(encoding='utf-8')); self.assertEqual(len(data), n)
        self.assertEqual(len(bib_records((out / 'references.bib').read_text(encoding='utf-8'))), n)
        self.assertEqual((out / 'references.ris').read_text(encoding='utf-8').count('ER  - '), n)
        self.assertEqual([c['citation-label'] for c in data], ['[1]', '[7]', '[10]', '[15]'])
        self.assertEqual([c.get('container-title') for c in data], ['BMJ', 'BMC Geriatr', 'JAMA', 'J Bone Miner Res'])
        self.assertEqual(data[2]['author'], [{'literal': 'US Preventive Services Task Force'}])
        rows = list(csv.DictReader(io.StringIO((out / 'studies.csv').read_text(encoding='utf-8'), newline='')))
        self.assertEqual([r['ref'] for r in rows], ['1', '7', '10', '15'])
        card = json.loads((d / 'card.json').read_text(encoding='utf-8'))
        self.assertEqual(sum(int(r['claims']) for r in rows), len(card['claims']))
        self.assertEqual(sum(int(r['found']) + int(r['distorted']) for r in rows), len(card['claims']))

if __name__ == '__main__':
    unittest.main()
