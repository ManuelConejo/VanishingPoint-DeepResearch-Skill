# SPDX-License-Identifier: Apache-2.0
"""R3-1 .. R3-3, R3-17 (regression specification): confidentiality before sending, provenance of gateway values, optional memory."""
import json
import re

from .am1_common import AM, VP, NOVP, load_tool, mutate, read_json, run_tool, sha, write_json
from .r3_common import R3, SYNTHETIC_CARDS

ARCHIVE_FILES = {
    'README.md': ("# Synthetic tile packing\nWe pack tiles quarterly with SoftFold paper folding and a removable felt sleeve.\n"
                  "Inspection-window folds use an embargo of one quarter between training and scoring windows.\n"),
    'results/LESSONS.md': ("# Lessons\nSoftFold on the painted-tile panel was tried: CLASSE, NE PAS ROUVRIR unless traywise groups change.\n"
                           "The cost model charges forty basis points per quarter of handling on painted tiles.\n"),
}
DRAFT = ("Free draft. Quantile plainfold forests might help title ranking according to Zanzibar benchmarks. "
         "Chameleon routing of queries across shards was noted in my memory.\n")


def windows(text, k=4):
    w = re.findall(r'[a-z0-9]+', text.lower())
    return [' '.join(w[i:i + k]) for i in range(len(w) - k + 1)]


class GuardBase(R3):
    def setUp(self):
        super().setUp()
        self.w = self.to_r3()
        root = self.tmp / 'proj'
        for rel, body in ARCHIVE_FILES.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding='utf-8')
        self.root = root
        mutate(self.w, 'intake.json', lambda d: d.update(project_dirs=[str(root)]))
        (self.w / 'free_draft.md').write_text(DRAFT, encoding='utf-8')
        self.vp = self.vp_fake({'find-implementations|*': {"index_total": None, "results": {"repos": [{"repo": "owner/name"}]}},
                                'repo-info|owner/name': {"results": {"id": "repo:owner/name", "licence": "MIT"}}})

    def run_matter(self, sub, *args):
        return run_tool('matter', sub, self.w, *args, '--vp', self.vp)

    def calls(self):
        p = self.tmp / 'fakevp' / 'tools' / 'calls.jsonl'
        return [l for l in p.read_text().splitlines() if l.strip()] if p.exists() else []

    def refused_clean(self, r):
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('refused before sending', r.stderr)
        self.assertEqual(self.calls(), [], 'the gateway was called')
        self.assertFalse((self.w / 'matter' / 'gw-001.json').exists())


class OutgoingGuardTest(GuardBase):
    def test_r3_1c_conforming_query_goes_once(self):
        r = self.run_matter('search', '--for', 'main', '--kind', 'code', '--query', 'title retrieval citations')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.calls()), 1)

    def test_r3_1a_every_archive_window_is_refused(self):
        # property: ALL 4-word windows of every archive file and of the draft (not in the idea) are refused by the guard
        idea = ' '.join([read_json(self.w / 'intake.json')['idea'], read_json(self.w / 'intake.json')['domain']])
        own = set(windows(idea))
        texts = list(ARCHIVE_FILES.values()) + [DRAFT]
        n = 0
        for t in texts:
            for win in windows(t):
                if win in own:
                    continue
                n += 1
                reasons = self.guards.check_outgoing(self.w, win)
                self.assertTrue(reasons, 'window not refused: %r' % win)
        self.assertGreater(n, 30)

    def test_r3_1a_a_passage_of_allowed_words_is_still_a_passage(self):
        # every word below is a word of the idea: neither the archive-word rule nor the whitelist can refuse the 4-word run,
        # only the passage rule can (it is the archive's own phrase, in an order the idea does not use)
        (self.root / 'notes.md').write_text('We keep citations shorter titles preprints as the baseline of the panel.\n', encoding='utf-8')
        q = 'citations shorter titles preprints'
        self.assertEqual(self.guards.check_outgoing(self.w, q), ['archive-passage'])
        self.assertEqual(self.guards.check_outgoing(self.w, 'preprints shorter citations titles'), [])      # control: another order
        self.refused_clean(self.run_matter('search', '--for', 'main', '--kind', 'code', '--query', q))
        (self.root / 'notes.md').unlink()
        self.assertEqual(self.guards.check_outgoing(self.w, q), [])

    def test_r3_1a_the_draft_passage_alone_is_refused_too(self):
        (self.w / 'free_draft.md').write_text('Notes. Search titles citations ranking retrieval again and again.\n', encoding='utf-8')
        self.assertEqual(self.guards.check_outgoing(self.w, 'titles citations ranking retrieval'), ['draft-passage'])

    def test_r3_1a_refusal_happens_before_the_call(self):
        for q in ('pack tiles quarterly with SoftFold paper folding',
                  'quantile plainfold forests might help title ranking'):
            self.refused_clean(self.run_matter('search', '--for', 'main', '--kind', 'code', '--query', q))

    def test_r3_1b_archive_only_word_refused_even_alone(self):
        for q in ('SoftFold', 'title SoftFold', 'embargo retrieval'):
            self.refused_clean(self.run_matter('search', '--for', 'main', '--kind', 'code', '--query', q))

    def test_r3_1b_every_archive_only_word_is_refused(self):
        idea = ' '.join([read_json(self.w / 'intake.json')['idea'], read_json(self.w / 'intake.json')['domain']]).lower()
        own = set(re.findall(r'[a-z0-9]+', idea))
        words = set(re.findall(r'[a-z]{5,}', ' '.join(ARCHIVE_FILES.values()).lower())) - own - self.guards.FUNCTION
        self.assertIn('softfold', words)
        for w_ in sorted(words):
            self.assertTrue(self.guards.check_outgoing(self.w, 'title ' + w_), w_)

    def test_r3_1b_query_terms_cannot_smuggle_an_archive_word(self):
        mutate(self.w, 'intake.json', lambda d: d['query_terms'].append('softfold'))
        self.refused_clean(self.run_matter('search', '--for', 'main', '--kind', 'code', '--query', 'title softfold'))

    def test_r3_1c_foreign_word_and_length_refused(self):
        self.refused_clean(self.run_matter('search', '--for', 'main', '--kind', 'code', '--query', 'title zebra'))
        long_q = ' '.join(['title'] * 13)
        self.refused_clean(self.run_matter('search', '--for', 'main', '--kind', 'code', '--query', long_q))

    def test_r3_1c_the_allowed_list_is_explicit(self):
        forms = self.guards.ALLOWED_FORMS
        self.assertGreaterEqual(len(forms), 3)
        self.assertEqual(self.guards.MAX_QUERY_WORDS, 12)

    def test_r3_1d_repo_form(self):
        self.assertEqual(self.run_matter('repo', '--for', 'main', '--repo', 'owner/name').returncode, 0)
        n = len(self.calls())
        for bad in ('owner/name extra words', '../etc/passwd', 'pack tiles quarterly with SoftFold', 'owner'):
            r = self.run_matter('repo', '--for', 'main', '--repo', bad)
            self.assertEqual(r.returncode, 1, (bad, r.stderr))
            self.assertEqual(len(self.calls()), n, bad)

    def test_r3_1e_moment_is_guarded(self):
        r = self.run_matter('moment', '--query', 'title SoftFold', '--years', '3')
        self.refused_clean(r)

    def test_r3_1_refusal_log_holds_no_leaked_text(self):
        self.run_matter('search', '--for', 'main', '--kind', 'code', '--query', 'title SoftFold')
        p = self.w / 'matter' / 'refused.jsonl'
        self.assertTrue(p.exists())
        body = p.read_text(encoding='utf-8').lower()
        self.assertNotIn('softfold', body)
        self.assertIn('sha256', body)

    def test_r3_1e_catalogue_with_work_is_guarded_before_any_call(self):
        out = self.tmp / 'cat'
        r = run_tool('catalogue', 'create', '--domain', 'scientometrics', '--out', out, '--vp', self.vp, '--work', self.w,
                     '--query', 'SoftFold')
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.calls(), [])
        self.assertIn('refused before sending', r.stderr)

    def test_r3_1_legacy_dir_still_gets_the_leak_guard(self):
        # a directory without R3 marker: the whitelist is off, the archive guard is on
        w = self.work(NOVP)
        mutate(w, 'intake.json', lambda d: d.update(project_dirs=[str(self.root)]))
        self.assertFalse(self.guards.check_outgoing(w, 'unrelated zebra words'))
        self.assertTrue(self.guards.check_outgoing(w, 'pack tiles quarterly with SoftFold paper folding'))

    def test_r3_3_none_refused_when_candidates_were_returned(self):
        self.assertEqual(self.run_matter('search', '--for', 'main', '--kind', 'code', '--query', 'title retrieval').returncode, 0)
        r = self.run_matter('none', '--for', 'main', '--kind', 'code')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('candidates', r.stderr)


class ProvenanceTest(R3):
    CANNED = {'repo-info|owner/name': {"index_total": None, "results": {
        "id": "repo:owner/name", "licence": "MIT", "at_T": {"sha": "abc", "date": "2026-03-02", "licence": "MIT"}}}}

    def setup_matter(self, digest, total=False):
        self.w = self.to_r3()
        self.vp = self.vp_fake(dict(self.CANNED), digest=digest, total=total)
        r = run_tool('matter', 'repo', self.w, '--for', 'main', '--repo', 'owner/name', '--vp', self.vp)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        mat = read_json(self.w / 'material.json')
        return mat['items'][0]

    def forge(self, item):
        p = self.w / item['envelope']
        env = read_json(p)
        env['gateway']['results']['at_T']['licence'] = 'Apache-2.0'
        env['gateway']['results']['licence'] = 'Apache-2.0'
        write_json(p, env)
        mutate(self.w, 'material.json', lambda d: d['items'][0].update(licence='Apache-2.0', envelope_sha256=sha(p)))

    def test_r3_2_attested_when_the_journal_agrees(self):
        it = self.setup_matter(digest=True)
        st, why = self.guards.provenance(self.w, it['envelope'])
        self.assertEqual(st, 'journal-attested', why)
        self.assertNoCode('[PROV')

    def test_r3_2_forged_envelope_with_rehash_is_caught_when_the_journal_has_the_digest(self):
        it = self.setup_matter(digest=True)
        self.forge(it)
        p = self.probs()
        self.assertTrue(self.code_in('[PROV-MISMATCH]', p), p)

    def test_r3_2_forgery_without_digest_is_never_shown_as_extracted(self):
        it = self.setup_matter(digest=False)
        self.forge(it)
        self.assertNoCode('[PROV-MISMATCH]')                     # nothing in the journal can contradict it
        st, _ = self.guards.provenance(self.w, it['envelope'])
        self.assertEqual(st, 'unverified provenance')
        self.assertEqual(self.card().returncode, 0, self.card().stdout)
        rep = (self.w / 'IDEA-REPORT.md').read_text(encoding='utf-8')
        line = next(l for l in rep.splitlines() if l.startswith('- main code'))
        self.assertIn('unverified provenance', line)
        self.assertNotIn('via gateway', line)
        self.assertNotIn('read from the saved gateway answer', rep.split('## Matter')[1].split('\n')[0])

    def test_r3_2_missing_journal_entry_means_unverified(self):
        it = self.setup_matter(digest=True)
        (self.w / 'matter' / 'state' / 'journal.jsonl').write_text('', encoding='utf-8')
        st, _ = self.guards.provenance(self.w, it['envelope'])
        self.assertEqual(st, 'unverified provenance')

    def test_r3_2_count_in_the_journal_must_match(self):
        it = self.setup_matter(digest=False)
        jp = self.w / 'matter' / 'state' / 'journal.jsonl'
        e = json.loads(jp.read_text().splitlines()[0])
        e['count'] = 7
        jp.write_text(json.dumps(e) + '\n')
        p = self.probs()
        self.assertTrue(self.code_in('[PROV-MISMATCH]', p), p)

    def test_r3_2_moment_total_fabricated_is_caught_or_marked(self):
        from .am1_common import AS_OFS, RISING, totals_for
        canned = totals_for(RISING, AS_OFS)
        self.w = self.to_r3()
        self.vp = self.vp_fake(canned, total=True)
        r = run_tool('matter', 'moment', self.w, '--query', 'title retrieval', '--years', '5', '--vp', self.vp)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        mo = read_json(self.w / 'moment.json')
        self.assertNotIn('unverified provenance', mo['line'])
        env_rel = mo['series'][-1]['envelope']
        p = self.w / env_rel
        env = read_json(p)
        env['gateway']['index_total'] = 99999
        write_json(p, env)
        def go(d):
            d['series'][-1]['envelope_sha256'] = sha(p)
            d['series'][-1]['total'] = 99999
        mutate(self.w, 'moment.json', go)
        probs = self.probs()
        self.assertTrue(self.code_in('[PROV-MISMATCH]', probs), probs)

    def test_r3_2_moment_without_journal_total_says_unverified_provenance(self):
        from .am1_common import AS_OFS, RISING, totals_for
        self.w = self.to_r3()
        self.vp = self.vp_fake(totals_for(RISING, AS_OFS), total=False)
        r = run_tool('matter', 'moment', self.w, '--query', 'title retrieval', '--years', '5', '--vp', self.vp)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('unverified provenance', read_json(self.w / 'moment.json')['line'])
        self.assertEqual(self.card().returncode, 0)
        c = (self.w / 'IDEA-CARD.md').read_text(encoding='utf-8')
        self.assertIn('unverified provenance', c)

    def test_r3_2_authority_is_stated(self):
        self.assertIn('journal', self.guards.AUTHORITY.lower())
        self.assertIn('VP', self.guards.AUTHORITY)


class MemoryOptionalTest(R3):
    def test_r3_17_no_archives_means_not_checked_without_penalty(self):
        w = self.to_r3()
        self.assertR3Clean()
        self.assertEqual(self.card().returncode, 0)
        c = (w / 'IDEA-CARD.md').read_text(encoding='utf-8')
        self.assertIn('Already tried here: not checked', c)
        warns = self.check.warnings(w)
        self.assertFalse([x for x in warns if 'HISTORY' in x], warns)
        self.assertEqual(read_json(w / 'recommendation.json')['verdict'], 'dig')

    def test_r3_17_softfold_case_with_archives(self):
        w = self.to_r3()
        root = self.tmp / 'proj'
        (root / 'lessons').mkdir(parents=True)
        (root / 'lessons' / 'LESSONS.md').write_text(
            '# Lessons\nSoftFold folding pattern on this panel: CLASSE, NE PAS ROUVRIR.\n', encoding='utf-8')
        mutate(w, 'intake.json', lambda d: d.update(project_dirs=[str(root)]))
        vp = self.vp_fake({'find-implementations|*': {"results": {"repos": [{"repo": "owner/name"}]}}})
        r = run_tool('matter', 'search', w, '--for', 'main', '--kind', 'code', '--query', 'title softfold', '--vp', vp)
        self.assertEqual(r.returncode, 1)
        self.assertFalse((self.tmp / 'fakevp' / 'tools' / 'calls.jsonl').exists())
