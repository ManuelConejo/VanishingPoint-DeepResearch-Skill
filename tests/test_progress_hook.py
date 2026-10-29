#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of the progress hook (tools/progress.py --hook, PostToolUse hook of the SKILL.md header, 29/10 trial): the line of a
step is shown once, in the order of config `progress.steps` (searches: again on each new searcher file), never for a sub-agent call,
a tool outside `progress.hook_tools` or a path outside a run; the run directory is found from file paths and from the words of a Bash
command (absolute or relative to the event's cwd); each line shown is logged in state/progress.log; the CLI prints {"systemMessage"}
and always exits 0; the shell command of the SKILL.md header finds the skill and relays the line, and does nothing without it."""
import contextlib, io, json, os, pathlib, shutil, subprocess, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent; ROOT = P.parent
sys.path.insert(0, str(ROOT / 'tools')); import progress as G, finish_run as F   # noqa: E702,E401
FX = P / 'fixtures' / 'finish_run'
SCOPE = '# Scope\n\nT = 2026-10-28. Plugin: biology. Mode: standard.\n\n## Criteria\n- x\n\n## Angles\n1. a\n2. b\n3. c\n4. d\n5. e\n\n## Waves\n'
CFG = json.loads((ROOT / 'tools' / 'config.json').read_text())['progress']


def header_command():
    head = (ROOT / 'SKILL.md').read_text().split('\n---\n', 1)[0]
    line = next(l for l in head.splitlines() if l.strip().startswith('command:'))
    v = line.split('command:', 1)[1].strip(); assert v[0] == v[-1] == "'"; return v[1:-1], head


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()); self.d = self.tmp / 'run'; (self.d / 'state').mkdir(parents=True)
        self.journal = [json.loads(l) for l in (FX / 'state' / 'journal.jsonl').read_text().splitlines() if l.strip()]

    def tearDown(self): shutil.rmtree(self.tmp)

    def ev(self, tool='Read', path=None, command=None, **kw):
        ti = {'file_path': str(path)} if path is not None else {'command': command}
        return dict({'hook_event_name': 'PostToolUse', 'tool_name': tool, 'tool_input': ti, 'cwd': str(self.tmp)}, **kw)

    def calls(self, rows):
        with open(self.d / 'state' / 'journal.jsonl', 'a') as f:
            for r in rows: f.write(json.dumps(r) + '\n')

    def log(self): return [json.loads(l) for l in (self.d / 'state' / CFG['log']).read_text().splitlines()]

    def test_sequence(self):
        self.assertIsNone(G.hook(self.ev('Write', self.d / 'scope.md')))                     # no scope.md yet: not a run
        (self.d / 'scope.md').write_text(SCOPE)
        self.assertEqual(G.hook(self.ev('Write', self.d / 'scope.md')), 'VP: framing done, 5 research angles, T = 2026-10-28.')
        self.assertIsNone(G.hook(self.ev('Write', self.d / 'scope.md')))                     # same step: shown once
        (self.d / 'searches').mkdir(); shutil.copy(FX / 'searches' / '1.md', self.d / 'searches' / '1.md'); self.calls(self.journal[:2])
        t = G.hook(self.ev('Read', self.d / 'searches' / '1.md')); self.assertIn('VP: searches, 1 searcher file(s); since last update 2 gateway call(s)', t)
        self.assertIsNone(G.hook(self.ev('Read', self.d / 'searches' / '1.md')))
        for n in (2, 3): shutil.copy(FX / 'searches' / f'{n}.md', self.d / 'searches' / f'{n}.md')
        self.calls(self.journal[2:])
        self.assertIn('3 searcher file(s)', G.hook(self.ev('Read', self.d / 'searches' / '3.md')))   # a new file: shown again
        (self.d / 'scope.md').write_text(SCOPE + '- Wave 1: 3 calls, 2 eligible.\n- Wave 2: 0 new. Wave 3: 0 new. Stop: two waves without new eligible.\n')
        self.assertIsNone(G.hook(self.ev('Edit', self.d / 'scope.md')))                      # still the searches step, no new file
        rep = (FX / 'REPORT.md').read_text(); (self.d / 'REPORT.md').write_text(rep[:rep.index('## Synthesis & Insights')])
        self.assertIn('writing the report (5 finding(s)', G.hook(self.ev('Write', self.d / 'REPORT.md')))
        (self.d / 'REPORT.md').write_text(rep)
        self.assertIn('extracting the claims', G.hook(self.ev('Edit', self.d / 'REPORT.md')))
        for f in ('card.json', 'result.json'): shutil.copy(FX / f, self.d / f)
        n = len(json.loads((FX / 'card.json').read_text())['claims'])
        cmd = f'python3 -I .claude/skills/vanishingpoint/tools/validate_card.py {self.d}'
        self.assertIn(f'verification of {n} claim(s)', G.hook(self.ev('Bash', command=cmd)))
        shutil.copy(FX / 'verdicts.json', self.d / 'verdicts.json')
        cmd = f'python3 -I tools/verifier.py verify --card {self.d}/card.json --out {self.d}/verdicts.json --state={self.d}/state'
        self.assertIn('VP: verification done', G.hook(self.ev('Bash', command=cmd)))
        with contextlib.redirect_stdout(io.StringIO()): F.finish(self.d, offline=True)
        t = G.hook(self.ev('Bash', command=f'python3 -I tools/finish_run.py run --T 2026-10-28', cwd=str(self.tmp)))   # relative path
        self.assertTrue(t.startswith('VP: finished.'), t)
        (self.d / 'REPORT.md').write_text(rep + '\n')                                         # back to deliver: never shown backwards
        self.assertIsNone(G.hook(self.ev('Edit', self.d / 'REPORT.md')))
        self.assertEqual([x['step'] for x in self.log()], ['framing', 'searches', 'searches', 'writing', 'annex', 'verify', 'verified', 'done'])
        self.assertEqual(CFG['steps'], ['framing', 'searches', 'writing', 'annex', 'verify', 'verified', 'done'])

    def test_ignored(self):
        (self.d / 'scope.md').write_text(SCOPE)
        self.assertIsNone(G.hook(self.ev('Write', self.d / 'scope.md', agent_id='a1')))       # sub-agent
        self.assertIsNone(G.hook(self.ev('Glob', self.d / 'scope.md')))                       # tool not in hook_tools
        self.assertIsNone(G.hook(self.ev('Read', self.tmp / 'elsewhere.md')))                 # not under a run
        self.assertIsNone(G.hook({'tool_name': 'Bash', 'tool_input': {'command': 'python3 -c "unbalanced'}}))
        self.assertIsNone(G.hook('not a dict')); self.assertIsNone(G.hook({}))
        self.assertFalse((self.d / 'state' / CFG['log']).exists())
        (self.d / 'scope.md').write_text('')                                                  # framing in progress: no line
        self.assertIsNone(G.hook(self.ev('Write', self.d / 'scope.md')))
        self.assertTrue(G.line(self.d).startswith('VP:'))                                     # the manual tool is unchanged

    def test_cli(self):
        (self.d / 'scope.md').write_text(SCOPE.replace('Mode: standard.', 'Mode: standard. Report language: fr.'))
        run = lambda inp: subprocess.run([sys.executable, '-I', str(ROOT / 'tools' / 'progress.py'), '--hook'], input=inp, capture_output=True, text=True)
        o = run(json.dumps(self.ev('Write', self.d / 'scope.md')))
        self.assertEqual(o.returncode, 0); self.assertEqual(json.loads(o.stdout), {'systemMessage': 'VP : cadrage fait, 5 angles de recherche, T = 2026-10-28.'})
        o = run(json.dumps(self.ev('Write', self.d / 'scope.md'))); self.assertEqual((o.returncode, o.stdout), (0, ''))
        o = run('{not json'); self.assertEqual((o.returncode, o.stdout), (0, ''))

    @unittest.skipUnless(shutil.which('sh'), 'no POSIX shell')
    def test_header_command(self):
        cmd, head = header_command()
        self.assertIn('PostToolUse:', head); self.assertIn('tools/progress.py" --hook', cmd)
        m = next(l for l in head.splitlines() if 'matcher:' in l).split('matcher:', 1)[1].strip().strip('"')
        self.assertEqual(m.split('|'), CFG['hook_tools'])
        (self.d / 'scope.md').write_text(SCOPE)
        proj = self.tmp / 'proj'; (proj / '.claude' / 'skills').mkdir(parents=True)
        os.symlink(ROOT, proj / '.claude' / 'skills' / 'vanishingpoint')
        env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(self.tmp / 'home'), 'CLAUDE_PROJECT_DIR': str(proj)}
        ev = json.dumps(self.ev('Write', self.d / 'scope.md'))
        o = subprocess.run(['sh', '-c', cmd], input=ev, capture_output=True, text=True, env=env)
        self.assertEqual(o.returncode, 0); self.assertIn('framing done', json.loads(o.stdout)['systemMessage'])
        env['CLAUDE_PROJECT_DIR'] = str(self.tmp / 'none')                                    # skill not found: silent, exit 0
        o = subprocess.run(['sh', '-c', cmd], input=ev, capture_output=True, text=True, env=env)
        self.assertEqual((o.returncode, o.stdout, o.stderr), (0, '', ''))


if __name__ == '__main__':
    unittest.main()
