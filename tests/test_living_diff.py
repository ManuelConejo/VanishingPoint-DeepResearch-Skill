#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of living_diff.py: two fixture runs (DOI case, arXiv version suffix, a source dated between T1 and T2 against older ones
seen or not at T1, a changed verdict, a dropped source, a new DISTORTED and a retraction mention), exit 2 on an incomplete dir, and, when the
fixture run `fixtures/living_run` (a trimmed copy of a real biology run, T 2026-10-28), a smoke test against an earlier modified copy:
the updated report, with the pasted paragraph, still passes the report checks of validate_card.py."""
import json, pathlib, re, shutil, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools')); import living_diff as L, validate_card as V   # noqa: E702
RUN = P / 'fixtures' / 'living_run'


def report(findings, biblio):
    f = ''.join(f'### Finding {i} — {t}\nThe sources establish it [1].\n\nVerdict: {v}.\n\n' for i, (t, v) in enumerate(findings, 1))
    return (f'# R\n\n## Executive Summary\n\nM helps on X [1]. More words follow.\n\n## Introduction\n\nT.\n\n## Main Analysis\n\n{f}'
            f'## Synthesis & Insights\n\nS.\n\n## Limitations & Caveats\n\nL.\n\n## Recommendations\n\nR.\n\n## Bibliography\n\n{biblio}\n\n'
            f'## Methodology Appendix\n\nSource coverage. Active: x. Skipped: none.\n\nOne-line summary: M helps.\n')


def make(d, T, sources, findings, statuses, seen=(), headers=None):
    d = pathlib.Path(d); (d / 'state').mkdir(parents=True)
    card = {'card_id': 'c', 'question': 'Does M help on X?', 'sources': {f'S{i}': dict(s[0], title=s[1]) for i, s in enumerate(sources, 1)},
            'claims': [{'id': f'A{i}', 'text': 't', 'source': {'key': k}, 'location': 'abstract'} for i, (k, _) in enumerate(statuses, 1)]}
    (d / 'card.json').write_text(json.dumps(card))
    (d / 'verdicts.json').write_text(json.dumps({'claims': [{'id': f'A{i}', 'status': s} for i, (_, s) in enumerate(statuses, 1)]}))
    bib = '\n'.join(f'[{i}] Author. {s[1]}. {s[2]}. {next(iter(s[0]))}:{next(iter(s[0].values()))}.{s[3] if len(s) > 3 else ""} Basis: abstract.'
                    for i, s in enumerate(sources, 1))
    (d / 'REPORT.md').write_text(report(findings, bib))
    (d / 'run.json').write_text(json.dumps({'T': [T], 'calls': 0}))
    (d / 'state' / 'journal.jsonl').write_text(json.dumps({'T': T, 'call': 'search-x', 'ids': list(seen)}) + '\n')
    for k, h in (headers or {}).items():
        (d / 'sources' / k).mkdir(parents=True); (d / 'sources' / k / 'source.txt').write_text(h + '\ntitle: t\n\nabstract')
    return d


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.old = make(self.tmp / 'old', '2025-03-01',
                        [({'doi': '10.1000/ABC.1'}, 'Alpha study', '2020'), ({'arxiv': '2401.00001v1'}, 'Beta preprint', '2024'),
                         ({'pmid': '111'}, 'Gamma trial', '2019')],
                        [('M improves recall on benchmarks (GO)', 'probable'), ('Cost is higher', 'open')],
                        [('S1', 'FOUND'), ('S2', 'FOUND'), ('S3', 'DISTORTED')], seen=['pmid:333'])
        self.new = make(self.tmp / 'new', '2026-10-28',
                        [({'doi': '10.1000/abc.1'}, 'Alpha study', '2020'), ({'arxiv': '2401.00001v3'}, 'Beta preprint', '2024', ' Retracted.'),
                         ({'pmid': '222'}, 'Delta trial', '2025'), ({'pmid': '333'}, 'Epsilon cohort', '2019'), ({'pmid': '444'}, 'Zeta cohort', '2018'),
                         ({'pmid': '555'}, 'Eta cohort', '2025')],
                        [('M improves recall on the benchmarks', 'established'), ('Cost is higher than baseline', 'open'), ('New harm signal', 'probable')],
                        [('S1', 'DISTORTED'), ('S2', 'FOUND'), ('S3', 'FOUND'), ('S4', 'FOUND')], seen=['pmid:111'],
                        headers={'S3': 'id: pmid:222 | doi: 10.9/D | year: 2025 | date: 2025-09-10'})
        self.d = L.compare(self.old, self.new)

    def tearDown(self): shutil.rmtree(self.tmp)

    def test_identifier_variants_match(self):
        self.assertEqual(len(self.d['sources_kept']), 2)              # DOI case and arXiv version suffix
        self.assertEqual(L.norm_id('doi', 'https://doi.org/10.48550/arXiv.2401.00001'), 'arxiv:2401.00001')
        self.assertEqual(L.norm_id('code', 'src/a.py:12-20@ABCDEF1234'), 'code:src/a.py@abcdef1')

    def test_added_classified(self):
        st = {s['title']: s['status'] for s in self.d['sources_added']}
        self.assertEqual(st['Delta trial'], 'new evidence')             # full date after T1
        self.assertEqual(st['Epsilon cohort'], 'older, seen at T1 but not kept')
        self.assertEqual(st['Zeta cohort'], 'older, not found at T1')
        self.assertTrue(st['Eta cohort'].startswith('undetermined'))   # same year as T1, no full date

    def test_dropped(self):
        self.assertEqual([(s['title'], s['status']) for s in self.d['sources_dropped']], [('Gamma trial', 'seen at T2 but not kept')])

    def test_findings_and_flags(self):
        ch = self.d['findings_verdict_changed']
        self.assertEqual(len(ch), 1); self.assertEqual((ch[0]['old']['words'], ch[0]['new']['words']), (['probable'], ['established']))
        self.assertEqual([c['new']['n'] for c in self.d['findings_verdict_same']], [2])
        self.assertEqual([f['title'] for f in self.d['findings_only_new']], ['New harm signal'])
        self.assertEqual([(x['n'], x['flags']) for x in self.d['newly_flagged']], [(2, ['retracted'])])
        self.assertEqual([x['n'] for x in self.d['newly_distorted']], [1])
        self.assertEqual((self.d['old']['counts']['DISTORTED'], self.d['new']['counts']['DISTORTED']), (1, 1))
        self.assertEqual(L.verdict_words('Verdict: NO-GO, then GO; open'), ['NO-GO', 'GO', 'open'])

    def test_outputs_and_paragraph(self):
        before = {p: p.read_bytes() for p in (self.old / 'REPORT.md', self.new / 'REPORT.md')}
        self.assertEqual(L.main([str(self.old), str(self.new)]), 0)
        self.assertTrue((self.new / 'UPDATE.md').exists()); js = json.loads((self.new / 'update.json').read_text())
        self.assertEqual(js['old']['T'], '2025-03-01')
        self.assertEqual(before, {p: p.read_bytes() for p in before})   # never edits a report
        par = L.paragraph(self.d)
        self.assertIn('[3]', par); self.assertNotIn('<', par); self.assertIn('Gamma trial', par)
        self.assertTrue({int(x) for x in re.findall(r'\[(\d+)\]', par)} <= set(range(1, 7)))

    def test_exit_2(self):
        (self.old / 'card.json').unlink()
        self.assertEqual(L.main([str(self.old), str(self.new), '--out', str(self.tmp / 'u' / 'UPDATE.md')]), 2)

    def test_smoke_real_run(self):
        new = self.tmp / 'bio-new'; old = self.tmp / 'bio-old'
        shutil.copytree(RUN, new); shutil.copytree(RUN, old)
        (old / 'run.json').write_text(json.dumps({'T': ['2025-06-01'], 'calls': 0}))
        t = (old / 'REPORT.md').read_text(encoding='utf-8')
        t = re.sub(r'^\[1\] .*\n', '', t, flags=re.M)                                          # [1]: 2026 meta-analysis, absent at T1
        t = re.sub(r'^\[13\] .*\n', '', t, flags=re.M)                                         # [13]: 2016, older, not found at T1
        t = t.replace('Verdict: probable (one guideline', 'Verdict: open (one guideline')       # finding 4
        t = t.replace('## Bibliography\n', '## Bibliography\n[99] Old et al. An earlier trial. 2012. pmid:99999999. Basis: abstract.\n')
        (old / 'REPORT.md').write_text(t, encoding='utf-8')
        c = json.loads((old / 'card.json').read_text()); c['sources'].pop('S1'); c['sources'].pop('S13'); (old / 'card.json').write_text(json.dumps(c))
        self.assertEqual(L.main([str(old), str(new)]), 0)
        d = json.loads((new / 'update.json').read_text())
        st = {s['n']: s['status'] for s in d['sources_added']}
        self.assertEqual(st[1], 'new evidence'); self.assertTrue(st[13].startswith('older'))
        self.assertEqual([s['ids'] for s in d['sources_dropped']], [['pmid:99999999']])
        self.assertEqual([(c['new']['n'], c['old']['words'], c['new']['words']) for c in d['findings_verdict_changed']], [(4, ['open'], ['probable'])])
        # the paragraph, pasted under a level-3 heading before the one-line summary, keeps the new report valid
        par = L.paragraph(L.compare(old, new)); r = (new / 'REPORT.md').read_text(encoding='utf-8')
        i = r.rindex('\n\nOne-line summary:')
        (new / 'REPORT.md').write_text(r[:i] + f'\n\n### What changed since 2025-06-01\n\n{par}' + r[i:], encoding='utf-8')
        t = (new / 'REPORT.md').read_text(encoding='utf-8')
        self.assertEqual(V.report_problems(t), []); self.assertIsNone(V.PLACEHOLDER.search(t))


if __name__ == '__main__':
    unittest.main()
