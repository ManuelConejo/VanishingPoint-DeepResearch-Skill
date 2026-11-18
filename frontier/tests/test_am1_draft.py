# SPDX-License-Identifier: Apache-2.0
"""AM1-AM15: the hybrid free draft (regression specification block A)."""
import json

from .am1_common import (AM, DRAFT, GOOD_REF, NOVP, Q_SLEEVE, Q_PADDING, Q_SMITH, VP, load_tool, mutate, read_json,
                         run_tool, sha, write_json)


def append_draft_text(work, text, fname='prior_art.json'):
    """Append `text` to the first transferable-method text of prior_art.json (a field that takes up the draft)."""
    def go(d):
        d['materials']['transferable_methods'][0]['text'] += ' ' + text
    mutate(work, fname, go)


class DraftCheckTest(AM):
    def test_am1_missing_claims(self):
        (self.work() / 'free_draft.md').write_text(DRAFT, encoding='utf-8')
        self.assertCode('[DRAFT-MISSING]')

    def test_absent_draft_changes_nothing(self):
        self.assertClean()
        self.assertNoCode('[DRAFT')

    def test_am2_schema_and_short(self):
        self.add_draft(claims=[{"id": "D1", "quote": Q_SLEEVE, "status": "maybe"}])
        self.assertCode('[SCHEMA] draft_claims.json')
        self.fresh()
        self.add_draft(draft='Too short.\n', claims=[{"id": "D1", "quote": "Too short.", "status": "unverified_memory"}])
        self.assertCode('[DRAFT-EMPTY]')

    def test_am3_stale(self):
        w = self.add_draft()
        (w / 'free_draft.md').write_text(DRAFT + 'A late edit of the draft after the claims were written.\n',
                                         encoding='utf-8')
        self.assertCode('[DRAFT-STALE]')

    def test_am4_quote_must_be_in_draft(self):
        self.add_draft(claims=[{"id": "D1", "quote": "A sentence that the draft never held at all", "status": "unverified_memory"}])
        self.assertCode('[DRAFT-QUOTE]')

    def test_am5_verified_needs_vp_reference(self):
        bad = {"id": "D1", "quote": Q_SLEEVE, "status": "verified", "ref": {"id": "doi:10.1000/ghost.2021", "run": "prior_art", "claim": "A4"}}
        self.add_draft(claims=[bad])
        self.assertCode('[DRAFT-VERIFY]')
        self.fresh()
        self.add_draft(claims=[{"id": "D1", "quote": Q_SLEEVE, "status": "verified"}])
        self.assertCode('[DRAFT-VERIFY]')
        self.fresh()
        invalid = dict(bad, ref={"id": "doi:10.1000/bad.2018", "run": "prior_art", "claim": "A5"})
        self.add_draft(claims=[invalid])
        self.assertCode('[DRAFT-VERIFY]')

    def test_am5_no_verified_without_vp(self):
        self.add_draft(NOVP, claims=[{"id": "D1", "quote": Q_SLEEVE, "status": "verified", "ref": dict(GOOD_REF)}])
        self.assertCode('[DRAFT-NOVP]', NOVP)

    def test_am6_candidates(self):
        hy = load_tool('hybrid')
        c = hy.candidates(DRAFT)
        kinds = {(x['kind'], x['text']) for x in c}
        self.assertTrue(any(k == 'reference' and 'Feltwick' in t for k, t in kinds), kinds)
        self.assertTrue(any(k == 'reference' and 'Smith' in t for k, t in kinds), kinds)
        self.assertTrue(any(k == 'identifier' and 'doi:10.1000/titles.2019' in t for k, t in kinds), kinds)
        numbers = {t for k, t in kinds if k == 'number'}
        for n in ('12.5%', '1,82', '0.27'):
            self.assertIn(n, numbers)
        for x in c:
            self.assertEqual(DRAFT[x['start']:x['end']], x['text'])

    def test_am6_scan_cli(self):
        w = self.add_draft()
        r = run_tool('hybrid', 'scan', w, '--json')
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertTrue(any(x['kind'] == 'reference' for x in out['candidates']))
        self.assertTrue(all('covered_by' in x for x in out['candidates']))

    def test_am7_taken_up_without_claim(self):
        w = self.add_draft(claims=[{"id": "D1", "quote": Q_SLEEVE, "status": "verified", "ref": dict(GOOD_REF)}])
        append_draft_text(w, 'Smith et al. (2019) report a gain.')
        p = self.assertCode('[DRAFT-UNMARKED]')
        self.assertTrue(any('Smith' in x for x in p if x.startswith('[DRAFT-UNMARKED]')))

    def test_am7_number_taken_up(self):
        w = self.add_draft(claims=[{"id": "D1", "quote": Q_SLEEVE, "status": "verified", "ref": dict(GOOD_REF)}])
        append_draft_text(w, 'The cradle padding ratio of 1,82 looks fragile.')
        self.assertCode('[DRAFT-UNMARKED]')

    def test_am7_unrelated_number_is_not_taken_up(self):
        w = self.add_draft(claims=[{"id": "D1", "quote": Q_SLEEVE, "status": "verified", "ref": dict(GOOD_REF)}])
        append_draft_text(w, 'Budget of 1,82 hours of reading per paper.')
        self.assertNoCode('[DRAFT-UNMARKED]')

    def test_am8_mark_required_for_memory_claims(self):
        w = self.add_draft()
        append_draft_text(w, 'Smith et al. (2019) report a gain.')
        self.assertCode('[DRAFT-MARK]')
        self.fresh()
        w = self.add_draft()
        append_draft_text(w, 'Smith et al. (2019) report a gain [unverified (memory)].')
        self.assertNoCode('[DRAFT-MARK]')
        self.assertNoCode('[DRAFT-UNMARKED]')

    def test_am9_verified_claim_passes_without_mark(self):
        w = self.add_draft()
        def go(d):
            d['hypotheses'][0]['statement'] += ' Feltwick et al. (2022) found felt sleeves beat paper cradles.'
        mutate(w, 'hypotheses.json', go)
        self.assertNoCode('[DRAFT')
        self.assertClean()

    def test_am10_removed_claim_taken_up(self):
        claims = [{"id": "D1", "quote": Q_SLEEVE, "status": "verified", "ref": dict(GOOD_REF)},
                  {"id": "D2", "quote": Q_SMITH, "status": "removed", "why": "could not be found by VP"}]
        w = self.add_draft(claims=claims)
        self.assertNoCode('[DRAFT')
        append_draft_text(w, 'Smith et al. (2019) report a gain.')
        self.assertCode('[DRAFT-REMOVED]')

    def test_am11_reference_object_needs_no_claim(self):
        # the identifier of the draft appears as a VP reference object of prior_art.json: VP verifies it already
        w = self.add_draft(claims=[{"id": "D1", "quote": Q_SLEEVE, "status": "verified", "ref": dict(GOOD_REF)}])
        self.assertNoCode('[DRAFT-UNMARKED]')
        self.assertTrue(any(c['ref']['id'] == 'doi:10.1000/titles.2019' for c in read_json(w / 'prior_art.json')['closest_work']))

    def test_am12_order(self):
        w = self.add_draft(step=False)
        self.assertCode('[DRAFT-ORDER]')
        def go(d):
            d['steps'].append({"step": "free_draft", "utc": "2026-11-14T11:00:00Z", "duration_s": "unknown",
                               "cost_usd": "unknown", "sha256": sha(w / 'free_draft.md')})
        mutate(w, 'run.json', go)
        self.assertCode('[DRAFT-ORDER]')

    def test_am12_step_hash_must_match(self):
        w = self.add_draft()
        def go(d):
            d['steps'][0]['sha256'] = '0' * 64
        mutate(w, 'run.json', go)
        self.assertCode('[DRAFT-STALE]')

    def test_good_draft_is_clean(self):
        self.add_draft()
        self.assertClean()
        self.fresh()
        self.add_draft(NOVP)
        self.assertClean(NOVP)


class DraftToolTest(AM):
    def test_am13_stub(self):
        w = self.work()
        (w / 'free_draft.md').write_text(DRAFT, encoding='utf-8')
        r = run_tool('hybrid', 'stub', w)
        self.assertEqual(r.returncode, 0, r.stderr)
        d = read_json(w / 'draft_claims.json')
        self.assertEqual(d['draft_sha256'], sha(w / 'free_draft.md'))
        self.assertGreaterEqual(len(d['claims']), 5)
        self.assertTrue(all(c['status'] == 'unverified_memory' for c in d['claims']))
        d['claims'][0]['why'] = 'edited by the host'
        write_json(w / 'draft_claims.json', d)
        r = run_tool('hybrid', 'stub', w)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(read_json(w / 'draft_claims.json')['claims'][0]['why'], 'edited by the host')

    def test_am14_step_records_hash(self):
        w = self.work()
        r = run_tool('step', w, '--step', 'free_draft')
        self.assertNotEqual(r.returncode, 0)
        (w / 'free_draft.md').write_text(DRAFT, encoding='utf-8')
        r = run_tool('step', w, '--step', 'free_draft')
        self.assertEqual(r.returncode, 0, r.stderr)
        last = read_json(w / 'run.json')['steps'][-1]
        self.assertEqual(last['step'], 'free_draft')
        self.assertEqual(last['sha256'], sha(w / 'free_draft.md'))

    def test_am92_new_steps_accepted(self):
        for s in ('context', 'evidence', 'matter', 'moment'):
            r = run_tool('step', self.work(), '--step', s)
            self.assertEqual(r.returncode, 0, (s, r.stderr))


class DraftCardTest(AM):
    def test_am15_card_line(self):
        self.add_draft()
        r = self.card()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        t = (self.work() / 'IDEA-CARD.md').read_text(encoding='utf-8')
        line = [l for l in t.splitlines() if l.startswith('Free draft')]
        self.assertEqual(len(line), 1, t)
        self.assertIn('4 claims', line[0])
        self.assertIn('2 verified', line[0])
        self.assertIn('2 unverified (memory)', line[0])
        self.assertLessEqual(len(t.splitlines()), 80)

    def test_card_has_no_free_draft_line_without_draft(self):
        self.assertEqual(self.card().returncode, 0)
        t = (self.work() / 'IDEA-CARD.md').read_text(encoding='utf-8')
        self.assertNotIn('Free draft', t)
