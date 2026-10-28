#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of check_keys.py with an empty HOME: plugin fixtures (English ```sources blocks written in a temp dir) are read, each
declared key is classified by the real resolution (key() / read_token()), a key placed in ~/.config/vp/ or in the environment is seen,
its value never appears, --json is JSON, exit code 0, mode line (standard / audit via VP_MODE or ~/.config/vp/mode)."""
import json, os, pathlib, subprocess, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent
TOOLS = P.parent / 'tools'
sys.path.insert(0, str(TOOLS)); import check_keys as ck, code_sources as sc   # noqa: E702

VARS = sorted(ck.CATALOGUE)
PLUGINS = {
    'biology.md': ('pubmed, europepmc, crossref, openalex, opencitations', 'OPENALEX_KEY, NCBI_API_KEY',
                   'pubmed=large PubMed searches, systematic review, meta-analysis, many clinical trials ; openalex=broad searches outside MEDLINE, citation chaining, grey literature'),
    'code.md': ('github, sourcegraph, code, versions, paper-code, provenance', 'VP_GITHUB_TOKEN, SWH_TOKEN',
                'github=literal code search in GitHub repositories, specific repository, licence, file, function, API, implementation ; software-heritage=provenance at volume, many repositories, archives, SWHID identifiers'),
    'cs-ai.md': ('openalex, crossref, arxiv, europepmc, dblp, semantic-scholar', 'OPENALEX_KEY, S2_API_KEY, OPENAIRE_TOKEN',
                 'semantic-scholar=citations, reference graph, recent cs/AI, citing articles, recommendations, state of the art ; openaire=European institutional repositories, funded projects, publication data software links ; openalex=broad searches, citation chaining, outside arXiv'),
    'finance.md': ('econbiz, openalex, crossref, europepmc, arxiv, edgar, fred', 'OPENALEX_KEY, FRED_API_KEY',
                   'fred=US macroeconomic series, rates, inflation, GDP, unemployment, point-in-time values, data revisions, ALFRED ; openalex=broad searches, working papers, citation chaining'),
    'law.md': ('eurlex, hudoc, judilibre, openalex', 'OPENALEX_KEY, PISTE_CLIENT_ID, PISTE_CLIENT_SECRET',
               'judilibre=French judicial case law, Court of Cassation, rulings, appeal, civil commercial social criminal chamber ; openalex=doctrine, legal articles, journals, citation chaining'),
}


def write_plugins(folder):
    out = {}
    for name, (engines, keys, uw) in PLUGINS.items():
        p = pathlib.Path(folder) / name
        p.write_text(f'# {name[:-3]} plugin (test fixture)\n\n```sources\nengines: {engines}   # wired or not\ncap: 60\nkeys: {keys}   # optional\n'
                     f'useful_when: {uw}\naccess: ' + ', '.join(e.strip() + '=api' for e in engines.split(',')) + '\n```\n', encoding='utf-8')
        out[name[:-3]] = p
    return out


class Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.home = pathlib.Path(self.tmp.name)
        self.env = {k: os.environ.pop(k) for k in VARS + ['HOME', 'VP_MODE'] if k in os.environ}
        os.environ['HOME'] = self.tmp.name
        self.saved = {k: getattr(sc, k, None) for k in ('TOKEN_PATH', 'FALLBACK_DIRS')}
        sc.TOKEN_PATH = None; sc.FALLBACK_DIRS = ()                                 # no fallback directory in a test
        (self.home / 'plugins').mkdir(); self.plugins = write_plugins(self.home / 'plugins')
        self.all = [self.plugins[k] for k in sorted(self.plugins)]

    def tearDown(self):
        for k in VARS + ['VP_MODE']: os.environ.pop(k, None)
        os.environ.update(self.env)
        for k, v in self.saved.items(): setattr(sc, k, v)
        self.tmp.cleanup()

    def test_empty_home_five_plugins(self):
        rep = ck.report(self.all)
        self.assertEqual([r['plugin'] for r in rep['plugins']], ['biology', 'code', 'cs-ai', 'finance', 'law'])
        for r in rep['plugins']:
            self.assertTrue(r['sources_block'], r['file']); self.assertTrue(r['keys_declared'], r['file'])
            self.assertEqual(set(r['keys_present']) | set(r['keys_absent']), set(r['keys_declared']))
            for k in r['keys_declared']:
                self.assertIn(k, ck.CATALOGUE, k)
                self.assertNotIn(k, r['keys_present'], (r['plugin'], k))                  # empty HOME, no fallback: no key
            self.assertTrue(set(r['active']) <= ck.WIRED and not set(r['not_wired']) & ck.WIRED)
        code = next(r for r in rep['plugins'] if r['plugin'] == 'code')
        self.assertEqual([i['variable'] for i in code['skipped']], ['VP_GITHUB_TOKEN'])          # GitHub skipped: token absent
        self.assertIn('code', code['active']); self.assertIn('https://github.com/settings/tokens', code['skipped'][0]['url'])
        self.assertNotIn('github', code['not_wired']); self.assertEqual(code['served_by']['github'], 'code')   # served by the wired code engine
        law = next(r for r in rep['plugins'] if r['plugin'] == 'law')
        self.assertEqual([i['variable'] for i in law['keyed_not_wired']], ['PISTE_CLIENT_ID + PISTE_CLIENT_SECRET'])
        self.assertEqual(law['keyed_not_wired'][0]['note'], ck.NOTE_NOT_WIRED)
        bio = next(r for r in rep['plugins'] if r['plugin'] == 'biology')
        self.assertEqual({i['variable']: i.get('note') for i in bio['degraded']}, {'OPENALEX_KEY': None, 'NCBI_API_KEY': None})
        self.assertIn('VP_GITHUB_TOKEN', rep['missing_keys']); self.assertFalse(rep['ok']); self.assertEqual(rep['mode'], 'standard')
        t = ck.text(rep)
        for word in ('biology.md', 'active', 'skipped', 'degraded', 'not wired', 'VP_GITHUB_TOKEN', 'KEYS.md'): self.assertIn(word, t)
        self.assertTrue(t.endswith('Mode: standard'), t[-80:])

    def test_key_file_and_env_seen_without_showing_the_value(self):
        (self.home / '.config' / 'vp').mkdir(parents=True)
        (self.home / '.config' / 'vp' / 's2_api_key.key').write_text('SECRET-S2-a1b2c3\n')
        (self.home / '.config' / 'vp' / 'empty.key').write_text('')
        os.environ['FRED_API_KEY'] = 'SECRET-FRED-z9y8'
        os.environ['VP_GITHUB_TOKEN'] = 'FAKE_SECRET_TOKEN_0123456789'
        rep = ck.report([self.plugins['cs-ai'], self.plugins['finance'], self.plugins['code']])
        by = {r['plugin']: r for r in rep['plugins']}
        self.assertIn('S2_API_KEY', by['cs-ai']['keys_present']); self.assertIn('FRED_API_KEY', by['finance']['keys_present'])
        self.assertIn('VP_GITHUB_TOKEN', by['code']['keys_present']); self.assertEqual(by['code']['skipped'], [])
        self.assertNotIn('FRED_API_KEY', rep['missing_keys'])
        out = ck.text(rep) + json.dumps(rep, ensure_ascii=False)
        for secret in ('SECRET-S2', 'SECRET-FRED', 'FAKE_SECRET'): self.assertNotIn(secret, out)
        saved = ck.sc.read_token
        def refused(): raise ValueError('malformed token')
        ck.sc.read_token = refused                                                  # refused by read_token: flagged invalid, never sent
        try: code = ck.report([self.plugins['code']])['plugins'][0]
        finally: ck.sc.read_token = saved
        self.assertEqual(code['skipped'][0]['state'], 'invalid'); self.assertIn('VP_GITHUB_TOKEN', code['keys_absent'])

    def test_announce_first_run_then_empty_then_key_added(self):
        plugins = [self.plugins['cs-ai'], self.plugins['code']]
        state = self.home / '.config' / 'vp' / 'keys-state.json'
        self.assertEqual(ck.state_path(), state)
        a1 = ck.announce(ck.report(plugins))                                   # first run: full announcement, state created
        self.assertTrue(a1.startswith('Keys: first run')); self.assertIn('https://github.com/settings/tokens', a1); self.assertTrue(state.is_file())
        self.assertIn('Mode: standard', a1)
        self.assertEqual(ck.announce(ck.report(plugins)), '')                 # second identical run: nothing
        self.assertEqual(ck.announce(ck.report([plugins[0]])), '')            # already known subset: nothing
        a3 = ck.announce(ck.report([self.plugins['finance']]))               # plugin never seen: announcement
        self.assertTrue(a3.startswith('Keys: the set')); self.assertIn('finance.md', a3)
        os.environ['VP_GITHUB_TOKEN'] = 'FAKE_SECRET_TOKEN_0123456789'           # key added: announcement, and the state holds no value
        a4 = ck.announce(ck.report(plugins))
        self.assertTrue(a4.startswith('Keys: the set')); self.assertIn('VP_GITHUB_TOKEN', a4); self.assertNotIn('FAKE_SECRET', a4)
        self.assertEqual(ck.announce(ck.report(plugins)), '')
        memo = json.loads(state.read_text()); self.assertNotIn('FAKE_SECRET', state.read_text())
        self.assertEqual(memo['plugins']['code']['keys_present'], ['VP_GITHUB_TOKEN']); self.assertIn('finance', memo['plugins'])
        del os.environ['VP_GITHUB_TOKEN']                                     # key removed or expired: announcement
        self.assertTrue(ck.announce(ck.report(plugins)).startswith('Keys: the set'))
        state.write_text('{not json')                                         # corrupted state = first run
        self.assertTrue(ck.announce(ck.report(plugins)).startswith('Keys: first run'))
        cmd = [sys.executable, '-I', str(TOOLS / 'check_keys.py'), '--announce', '--plugin', str(plugins[0])]
        for _ in range(2):   # command line (real process): at most one announcement, then nothing when nothing changed
            p = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, 'HOME': self.tmp.name}, timeout=60)
        self.assertEqual((p.returncode, p.stdout), (0, ''), p.stderr)

    def test_suggest_free_source_when_the_question_gains(self):
        bio, law, csai, code = self.plugins['biology'], self.plugins['law'], self.plugins['cs-ai'], self.plugins['code']
        s = ck.suggest(ck.report([bio]), 'vitamin D meta-analysis of clinical trials, systematic review')   # NCBI key is sent -> suggested
        self.assertEqual([x['source'] for x in s], ['PubMed with an NCBI key']); self.assertEqual(s[0]['variable'], 'NCBI_API_KEY')
        self.assertIn('free registration', s[0]['text'])
        # A declared key with no effect today (engine not wired, or key not passed) is never suggested, however well it matches.
        self.assertEqual(ck.suggest(ck.report([law]), 'case law Court of Cassation commercial lease'), [])            # Judilibre: not wired
        self.assertEqual(ck.suggest(ck.report([csai]), 'citation graph and citing articles in recent AI'), [])       # Semantic Scholar: not wired
        self.assertEqual([x['variable'] for x in ck.suggest(ck.report([code]), 'provenance of many repositories in archives')], ['SWH_TOKEN'])   # SWH_TOKEN: sent since v0.3.1
        self.assertEqual(ck.suggest(ck.report([code]), 'licence of a specific repository file')[0]['variable'], 'VP_GITHUB_TOKEN')
        self.assertEqual(ck.suggest(ck.report([csai, law]), 'graph neural networks'), [])          # "graph" alone is not enough
        self.assertLessEqual(len(ck.suggest(ck.report(self.all), 'meta-analysis clinical trials systematic review citation chaining specific repository licence file')), 2)
        for f in self.all: self.assertTrue(ck.useful_when(f), f.name)                                # each fixture declares useful_when
        p = subprocess.run([sys.executable, '-I', str(TOOLS / 'check_keys.py'), '--suggest', 'vitamin D meta-analysis of clinical trials, systematic review', '--plugin', str(bio)],
                           capture_output=True, text=True, env={**os.environ, 'HOME': self.tmp.name}, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr); self.assertIn('NCBI_API_KEY', p.stdout)
        p = subprocess.run([sys.executable, '-I', str(TOOLS / 'check_keys.py'), '--suggest', 'case law Court of Cassation commercial lease', '--plugin', str(law)],
                           capture_output=True, text=True, env={**os.environ, 'HOME': self.tmp.name}, timeout=60)
        self.assertEqual((p.returncode, p.stdout), (0, ''), p.stderr)

    def test_mode_standard_or_audit(self):
        self.assertEqual(ck.mode(), 'standard'); self.assertEqual(ck.mode_line(), 'Mode: standard')
        os.environ['VP_MODE'] = 'audit'
        self.assertEqual(ck.mode(), 'audit'); self.assertTrue(ck.mode_line().startswith('Mode: audit ('))
        self.assertTrue(ck.text(ck.report([self.plugins['biology']])).endswith('Mode: audit (set by VP_MODE|~/.config/vp/mode)'))
        os.environ['VP_MODE'] = 'standard'
        self.assertEqual(ck.mode(), 'standard')
        del os.environ['VP_MODE']
        (self.home / '.config' / 'vp').mkdir(parents=True, exist_ok=True)
        (self.home / '.config' / 'vp' / 'mode').write_text(' audit \n')
        self.assertEqual(ck.mode(), 'audit'); self.assertEqual(ck.report([self.plugins['biology']])['mode'], 'audit')
        (self.home / '.config' / 'vp' / 'mode').write_text('standard\n')
        self.assertEqual(ck.mode(), 'standard')
        p = subprocess.run([sys.executable, '-I', str(TOOLS / 'check_keys.py'), '--plugin', str(self.plugins['biology'])],
                           capture_output=True, text=True, env={**os.environ, 'HOME': self.tmp.name, 'VP_MODE': 'audit'}, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr); self.assertTrue(p.stdout.rstrip().endswith('Mode: audit (set by VP_MODE|~/.config/vp/mode)'))

    def test_contradictors_line_names_only(self):
        saved = {k: os.environ.get(k) for k in ('VP_CONTRADICTORS', 'OPENROUTER_API_KEY', 'GEMINI_API_KEY', 'VP_CONTRADICTOR_PROVIDERS')}
        try:
            for k in saved: os.environ.pop(k, None)
            self.assertEqual(ck.contradictors(), []); self.assertTrue(ck.contradictors_line().startswith('Contradictors: none (')); self.assertIn('openrouter', ck.contradictors_line())
            t = ck.text(ck.report([self.plugins['code']])); self.assertLess(t.index('Contradictors: none'), t.index('Mode: standard')); self.assertTrue(t.endswith('Mode: standard'))
            os.environ['VP_CONTRADICTORS'] = 'OpenRouter:Vendor/Model-1, openai, gemini:m'
            self.assertEqual(ck.contradictors(), ['openrouter:vendor/model-1', 'openai', 'gemini:m'])
            self.assertEqual(ck.contradictors_line(), 'Contradictors: openrouter:vendor/model-1 (OPENROUTER_API_KEY absent: skipped, credential_missing), openai, gemini:m (GEMINI_API_KEY absent: skipped, credential_missing) (set by VP_CONTRADICTORS|~/.config/vp/contradictors|tools/config.json)')
            os.environ['OPENROUTER_API_KEY'] = 'SECRET-OPENROUTER-VALUE'; os.environ['GEMINI_API_KEY'] = 'SECRET-GEMINI-VALUE'
            line = ck.contradictors_line(); self.assertIn('(OPENROUTER_API_KEY present)', line); self.assertIn('(GEMINI_API_KEY present)', line); self.assertNotIn('SECRET-', line)
            os.environ['VP_CONTRADICTORS'] = 'nope:m, ollama:m'; self.assertEqual(ck.contradictors_line(), 'Contradictors: nope:m (unknown provider: skipped), ollama:m (set by VP_CONTRADICTORS|~/.config/vp/contradictors|tools/config.json)')
            os.environ['VP_CONTRADICTOR_PROVIDERS'] = json.dumps({'nope': {'url': 'http://x', 'key': None}}); self.assertIn('nope', ck.providers()); self.assertNotIn('unknown provider', ck.contradictors_line())
            os.environ.pop('VP_CONTRADICTORS'); d = pathlib.Path.home() / '.config' / 'vp'; d.mkdir(parents=True, exist_ok=True)
            (d / 'contradictors').write_text('claude  # comment\nopenrouter:a/b\n'); self.assertEqual(ck.contradictors(), ['claude', 'openrouter:a/b']); (d / 'contradictors').unlink()
            self.assertEqual(ck.report([self.plugins['code']])['contradictors'], [])
        finally:
            for k, v in saved.items():
                if v is None: os.environ.pop(k, None)
                else: os.environ[k] = v

    def test_command_line_json_exit_0(self):
        env = {**os.environ, 'HOME': self.tmp.name}
        p = subprocess.run([sys.executable, '-I', str(TOOLS / 'check_keys.py'), '--json', '--plugin', str(self.plugins['biology'])],
                           capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        rep = json.loads(p.stdout)
        self.assertEqual([r['plugin'] for r in rep['plugins']], ['biology']); self.assertIn('missing_keys', rep); self.assertEqual(rep['mode'], 'standard')
        p = subprocess.run([sys.executable, '-I', str(TOOLS / 'check_keys.py')], capture_output=True, text=True, env=env, timeout=60)   # default: plugins/ of the skill
        self.assertEqual(p.returncode, 0, p.stderr); self.assertIn('Missing keys', p.stdout); self.assertIn('Mode: standard', p.stdout)
        shipped = sorted(p.name for p in (TOOLS.parent / 'plugins').glob('*.md') if not p.name.startswith('_'))
        if shipped:                                                            # shipped plugins, when present: every declared key is in the catalogue
            rep = ck.report()
            self.assertEqual([r['plugin'] + '.md' for r in rep['plugins']], shipped)
            for r in rep['plugins']:
                self.assertTrue(r['sources_block'], r['file']); self.assertFalse(r.get('unknown_keys'), r)


if __name__ == '__main__':
    unittest.main()
