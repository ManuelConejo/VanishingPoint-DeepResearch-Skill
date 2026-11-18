# SPDX-License-Identifier: Apache-2.0
"""Shared helpers of the history tests (regression specification). No network, no model.

Invented workshop archives include encoded French text for normalization tests.
The project holds a CLASSED packing trial, a lessons file and a preparation
script with objective="plainfold". None of the script is executed."""
import json
import os
import shutil
from pathlib import Path

from .helpers import TempCase, load_tool, mutate, read_json, run_tool, write_json

E_ACUTE, E_CAPS = '\xe9', '\xc9'

RESULTS = (
    '# SoftFold vs PlainFold (caf\u00e9 tile packing; protection d\'angles)\n'  # 1
    '\n'  # 2
    'Protocol: PaperKit, objective="softfold" versus objective="plainfold", same tiles, same inspection-window.\n'  # 3
    '\n'  # 4
    '| cradle | padding |\n'  # 5
    '|--------|---------|\n'  # 6
    '| plainfold | 1.00 |\n'  # 7
    '| softfold | 0.37 |\n'  # 8
    '\n'  # 9
    'Verdict : -63 % padding for SoftFold. CLASS\xc9.\n'  # 10
    '\n'  # 11
    '## RE-VISIT\xc9\n'  # 12
    '\n'  # 13
    'Broken design (tray groups mixed): repeat the packing comparison with groups per date.\n'  # 14
    'Verdict stays CLASS\xc9 / NE PAS ROUVRIR now.\n'  # 15
    'R\u00e9ouverture conditionnelle des berceaux de papier dans research/fold/FOLD_PACKING_SUMMARY.md.\n'  # 16
    'Never propose FOLD again without citing this file.\n'  # 17
)
LESSONS = (
    '# LESSONS (synthetic)\n'  # 1
    '\n'  # 2
    '- Freeze the inspection-window before comparing two cradle designs.\n'  # 3
    '- The paper folding cradle was tried (status: test\u00e9) with 3 sleeve thicknesses; the spread is 0.05 padding units.\n'  # 4
    '- The workshop review proposed Soft-Fold as packing option #1 before finding softfold already tried and CLASS\xc9.\n'  # 5
    '- Sketches are not evidence: every cited inspection result comes from results/.\n'  # 6
)
FOLD_SUMMARY = (
    '# FOLD summary (synthetic)\n'  # 1
    '\n'  # 2
    'Soft-Fold was tried twice for painted wooden tile packing.\n'  # 3
    '\n'  # 4
    'Conditional reopening: reopen FOLD only if tray groups are rebuilt per date AND more than 500 tiles per date are available.\n'  # 5
)
TRAIN = (
    '"""Synthetic packing preparation script; never executed."""\n'  # 1
    'import paperkit as kit\n'  # 2
    '\n'  # 3
    'PARAMS = {\n'  # 4
    '    "objective": "plainfold",   # paper folding baseline for tile packing\n'  # 5
    '    "fold_depth": 0.05,\n'  # 6
    '    "corner_count": 31,\n'  # 7
    '}\n'  # 8
    '\n'  # 9
    '\n'  # 10
    'def prepare(tiles, sizes):\n'  # 11
    '    return kit.prepare(PARAMS, tiles, sizes, rounds=300)\n'  # 12
)
EN_SUMMARY = (
    "Corner trimming by edge removal: REJECTED after the ablation run.\n"
    "DO NOT REOPEN unless the number of features triples.\n"
    "Reopen if the universe grows beyond 2000 tiles.\n"
)
GOOD_FILES = {
    'results/test_softfold.md': RESULTS,
    'LESSONS.md': LESSONS,
    'research/fold/FOLD_PACKING_SUMMARY.md': FOLD_SUMMARY,
    'scripts/prepare_cradle.py': TRAIN,
    'notes/en_summary.txt': EN_SUMMARY,
}
# content that must never be read: ignored directories, other extensions, binary data, links
BAD_TEXT = 'softfold CLASS\xc9 NE PAS ROUVRIR (must never be read)\n'
IGNORED_FILES = {
    '.git/notes.txt': BAD_TEXT,
    'venv/lib/site.py': '# ' + BAD_TEXT,
    '.venv/lib/site.py': '# ' + BAD_TEXT,
    'node_modules/pkg/README.md': BAD_TEXT,
    '__pycache__/x.py': '# ' + BAD_TEXT,
    'data/prices.csv': 'date,softfold\n2020-01-01,1\n',
    'data/conf.toml': 'name = "softfold"\n',
}
BINARY = {
    'data/model.pkl': b'\x00\x01softfold CLASS\xc3\x89\x00',
    'data/blob.json': b'{"x": "softfold CLASS\xc3\x89"}\x00\x00',
    'data/blob.txt': b'\x00softfold CLASS\xc3\x89',
}


def write_files(root, files):
    root = Path(root)
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding='utf-8')
    return root


def build_project(root, ignored=True, links=True):
    write_files(root, GOOD_FILES)
    if ignored:
        write_files(root, IGNORED_FILES)
        write_files(root, BINARY)
    if links:
        try:
            os.symlink(str(Path(root) / 'results' / 'test_softfold.md'), str(Path(root) / 'results' / 'link.md'))
            os.symlink(str(Path(root) / 'results'), str(Path(root) / 'linkdir'))
        except (OSError, NotImplementedError):
            pass
    return Path(root)


IDEA = ('Replace our paper folding model for tile packing with a different folding pattern. '
        'The goal is a better held-out-batch padding ratio.')
INTAKE_TERMS = [
    {'term': 'paper folding', 'synonyms': ['paperkit', 'CRADLE'], 'group': 'idea'},
    {'term': 'tile packing', 'synonyms': ['tile protection', 'wooden tile packing', "protection d'angles"], 'group': 'idea'},
    {'term': 'corner trimming', 'synonyms': ['edge removal'], 'group': 'neighbour'},
]
FOLD_TITLE = 'Same paper cradle with a folding pattern (SoftFold) versus the plainfold objective'
FOLD_TERM = {'term': 'softfold', 'synonyms': ['soft fold', 'FOLD'], 'group': 'test'}


class HB(TempCase):
    """Base of the history tests: a synthetic project in self.proj, helpers around the CLI of tools/history.py."""

    def setUp(self):
        super().setUp()
        self.check = load_tool('check')
        self.history = load_tool('history')
        self.proj = self.tmp / 'project'
        build_project(self.proj)
        self.n_terms = 0

    # ---- project and files
    def line_of(self, rel, needle, root=None):
        text = (Path(root or self.proj) / rel).read_text(encoding='utf-8')
        for i, line in enumerate(text.splitlines(), 1):
            if needle in line:
                return i
        raise KeyError(needle)

    def terms_file(self, terms, label=None):
        self.n_terms += 1
        p = self.tmp / ('terms-%d.json' % self.n_terms)
        write_json(p, {'terms': terms})
        return p

    # ---- history.py
    def scan(self, work, label, terms, *extra, dirs=None, tools_dir=None):
        args = ['scan', work, '--label', label, '--terms-file', self.terms_file(terms)]
        for d in (dirs or []):
            args += ['--project-dir', d]
        args += list(extra)
        return run_tool('history', *args, tools_dir=tools_dir)

    def scan_ok(self, work, label, terms, *extra, dirs=None, tools_dir=None):
        r = self.scan(work, label, terms, *extra, dirs=dirs, tools_dir=tools_dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return self.hist(work)

    def hist(self, work):
        return read_json(Path(work) / 'history.json')

    def entries(self, work, rel=None):
        return [e for e in self.hist(work)['entries'] if rel is None or e['file'] == rel]

    def entry(self, work, rel, needle=None):
        """The entry of file `rel` whose line holds `needle` (or the first entry of that file)."""
        line = self.line_of(rel, needle) if needle else None
        for e in self.entries(work, rel):
            if line is None or e['line'] == line:
                return e
        raise KeyError((rel, needle))

    # ---- working directories
    def new_work(self, base='valid_novp', name='hw', idea=True, dirs=True):
        dest = self.fx / name
        shutil.copytree(str(self.work(base)), str(dest))

        def go(d):
            if idea:
                d['idea'] = IDEA
            if dirs:
                d['project_dirs'] = [str(self.proj)]
        mutate(dest, 'intake.json', go)
        if idea:                                    # the rebound files name the idea of the intake as their parent
            for name in ('rebound.json', 'rebound_after.json'):
                if (dest / name).exists():
                    mutate(dest, name, lambda d: d.update(parent_idea=IDEA))
        return dest

    def removal_note(self, e, **over):
        n = {'cited': '%s:%d' % (e['file'], e['line']), 'what': 'A SoftFold test of the same model (first proposal)',
             'why': 'Classed in results/test_softfold.md; the written reopening condition is not met.'}
        n.update(over)
        return n

    def set_fold_test(self, work, test='T2', title=FOLD_TITLE):
        def go(d):
            for t in d['tests']:
                if t['id'] == test:
                    t['title'] = title
                    t['decisive_intervention']['description'] = (
                        'Train the same paper folding model with a SoftFold objective and with the plainfold '
                        'objective on identical folds, then compare the held-out-batch padding ratio.')
        mutate(work, 'tests.json', go)

    def terms_for_tests(self, work, fold=True):
        ids = [t['id'] for t in read_json(Path(work) / 'tests.json')['tests']]
        terms = []
        for tid in ids:
            if tid == 'T2' and fold:
                terms.append(dict(FOLD_TERM, **{'for': tid}))
            else:
                terms.append({'term': 'title length', 'synonyms': [], 'group': 'test', 'for': tid})
        return terms

    def rebound_terms(self, work, overrides=None):
        ids = []
        for name in ('rebound.json', 'rebound_after.json'):
            if (Path(work) / name).exists():
                ids += [i['id'] for i in read_json(Path(work) / name)['ideas']]
        return [dict((overrides or {}).get(i, {'term': 'abstract coverage', 'synonyms': [], 'group': 'neighbour'}),
                     **{'for': i}) for i in ids]

    def full_flow(self, base='valid_novp', name='hw', fold=True):
        """Intake scan, the SoftFold test in T2, tests scan. Returns the working directory (no citation yet)."""
        work = self.new_work(base, name)
        self.scan_ok(work, 'intake', INTAKE_TERMS)
        if fold:
            self.set_fold_test(work)
        self.scan_ok(work, 'tests', self.terms_for_tests(work, fold))
        return work

    # ---- citations
    def cite(self, work, rel, needle, **over):
        e = self.entry(work, rel, needle)
        item = {
            'entry': e['id'], 'cited': '%s:%d' % (e['file'], e['line']),
            'verdict_quoted': 'CLASS' + E_CAPS,
            'decision': 'kept',
            'reopen_condition': ('reopen FOLD only if tray groups are rebuilt per date AND '
                                 'more than 500 tiles per date are available'),
            'reopen_condition_source': 'research/fold/FOLD_PACKING_SUMMARY.md:5',
            'condition_met': ('The tray groups are rebuilt per date and the universe has 800 tiles per date, '
                              'so both written conditions hold for this packing test.'),
        }
        item.update(over)
        return {k: v for k, v in item.items() if v is not None}     # an override of None drops the key

    def good_citations(self, work):
        return [self.cite(work, 'results/test_softfold.md', 'Verdict : -63'),
                self.cite(work, 'LESSONS.md', 'softfold')]

    def attach(self, work, items, test='T2', fname='tests.json'):
        def go(d):
            for t in d['tests']:
                if t['id'] == test:
                    t['internal_history'] = items
        mutate(work, fname, go)

    def problems(self, work):
        return self.check.problems(work)

    def codes(self, work):
        return ' | '.join(self.problems(work))

    def assertCode(self, code, work, text=None):
        probs = self.problems(work)
        hit = [p for p in probs if p.startswith(code)]
        self.assertTrue(hit, '%s not in %r' % (code, probs))
        if text:
            self.assertTrue(any(text in p for p in hit), '%r not in %r' % (text, hit))
        return probs

    def assertNoCode(self, code, work):
        probs = self.problems(work)
        self.assertFalse(any(p.startswith(code) for p in probs), '%s in %r' % (code, probs))
