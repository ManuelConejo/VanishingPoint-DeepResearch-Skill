# SPDX-License-Identifier: Apache-2.0
"""Observable guarantees of regression specification. Local fixtures only; no model or network."""
import copy
import hashlib
import re
from pathlib import Path
from unittest.mock import patch

from .v2_common import V2, VP, load_tool, mutate, read_json, run_tool, write_json
from .r3_common import REBOUND
from .test_v2_rebound import plan_of
from .helpers import FRONTIER


LEADS = ['Compare thick felt inserts with equal paper padding at a preparation cost of 0.25%.',
    'Use a frozen packing assignment to compare sleeve durability across washing cycles.',
    'Replace the straight sleeve seam with a rounded corner joint for circular wooden tiles.',
    'Audit packing assignments against a sealed tray list before inspecting any surface marks.',
    'Separate volunteer practice effects from persistent protection by the felt material.',
    'Measure protection on held-out tile shapes using the same masking and inspection rubric.',
    'Keep corner chips as a distinct outcome rather than pooling them with broad face scratches.',
    'Study missing contact between a stiff paper fold and the curved edge of a painted wooden disc.',
    'Test sleeve fit after delayed washing using the original frozen dimension gauge.']


class FreePhaseTest(V2):
    def setUp(self):
        super().setUp()
        self.w = self.to_v2()

    def draft(self, count=9):
        draft = '\n'.join(LEADS[:count]) + '\n'
        (self.w / 'free_draft.md').write_text(draft, encoding='utf-8')
        digest = hashlib.sha256(draft.encode('utf-8')).hexdigest()
        write_json(self.w / 'draft_claims.json', {
            'draft_sha256': digest,
            'claims': [{'id': 'D%d' % (i + 1), 'quote': q, 'status': 'unverified_memory'}
                       for i, q in enumerate(LEADS[:count])]})
        mutate(self.w, 'run.json', lambda d: d['steps'].insert(0, {
            'step': 'free_draft', 'utc': '2026-11-14T08:00:00Z',
            'duration_s': 'unknown', 'cost_usd': 'unknown', 'sha256': digest}))

    def submit(self, ids=None):
        ids = ids or ['D1', 'D2', 'D3', 'D4', 'D5']
        r = run_tool('hybrid', 'submit', self.w, '--run', 'prior_art', '--claims', *ids,
                     '--sources', *(['S1'] * len(ids)),
                     '--why', 'These claims determine the next action and the baseline to compare.')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return read_json(self.w / 'draft_claims.json')

    def verdicts(self, status='FOUND'):
        d = read_json(self.w / 'draft_claims.json')
        vp = self.fx / 'vp_prior_art'
        card = read_json(vp / 'card.json')
        rows = []
        for c in d['claims']:
            if c.get('verification'):
                cid = c['verification']['claim']
                text = next(x['text'] for x in card['claims'] if x['id'] == cid)
                rows.append({'id': cid, 'text': text, 'source': 'S1', 'status': status,
                             'fragments': [text] if status == 'FOUND' else []})
        mutate(vp, 'verdicts.json', lambda v: v['claims'].extend(rows))

    def test_zero_submission_fails_checker_and_cli(self):
        self.draft()
        self.assertBlocks('[DRAFT-NOSUBMIT]')
        r = run_tool('check', self.w)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('[DRAFT-NOSUBMIT]', r.stdout)

    def test_under_inventory_cannot_bypass_zero_submission_check(self):
        self.draft()
        mutate(self.w, 'draft_claims.json', lambda d: d.update(claims=d['claims'][:1]))
        self.assertBlocks('[DRAFT-NOSUBMIT]')

    def test_v2_stub_keeps_full_prose_claims_and_numeric_leads(self):
        self.draft()
        (self.w / 'draft_claims.json').unlink()
        r = run_tool('hybrid', 'stub', self.w)
        self.assertEqual(r.returncode, 0, r.stderr)
        claims = read_json(self.w / 'draft_claims.json')['claims']
        self.assertEqual([c['quote'] for c in claims], LEADS)
        self.assertTrue(all(c['status'] == 'unverified_memory' for c in claims))

    def test_leads_and_magnitudes_are_independent_and_only_duplicates_merge(self):
        self.draft()
        hy = load_tool('hybrid')
        rich = hy.richness(self.w)
        self.assertEqual(rich['leads'], 9)
        self.assertGreaterEqual(rich['magnitudes'], 1)
        mutate(self.w, 'draft_claims.json', lambda d: d['claims'].append(
            dict(d['claims'][0], id='D10', quote='  ' + LEADS[0] + '  ')))
        self.assertEqual(hy.richness(self.w)['leads'], 9)

    def test_submit_preserves_original_card_and_links_exact_quotes(self):
        self.draft()
        before = read_json(self.fx / 'vp_prior_art' / 'card.json')
        d = self.submit(['D2', 'D4', 'D5', 'D6', 'D9'])
        after = read_json(self.fx / 'vp_prior_art' / 'card.json')
        self.assertEqual(after['claims'][:len(before['claims'])], before['claims'])
        self.assertEqual(after['sources'], before['sources'])
        self.assertEqual(len(after['claims']) - len(before['claims']), 5)
        selected = [c for c in d['claims'] if c.get('verification')]
        self.assertEqual({c['id'] for c in selected}, {'D2', 'D4', 'D5', 'D6', 'D9'})
        for c in selected:
            actual = next(x for x in after['claims'] if x['id'] == c['verification']['claim'])
            self.assertEqual(actual['text'], c['quote'])
            self.assertEqual(actual['source'], {'key': 'S1'})
        self.assertTrue(all(c['status'] == 'unverified_memory' for c in d['claims']))
        self.assertMarks('[DRAFT-VERDICT]')

    def test_submit_refuses_unknown_source_without_modifying_files(self):
        self.draft()
        paths = [self.w / 'draft_claims.json', self.fx / 'vp_prior_art' / 'card.json']
        before = [p.read_bytes() for p in paths]
        r = run_tool('hybrid', 'submit', self.w, '--run', 'prior_art',
                     '--claims', 'D1', 'D2', 'D3', 'D4', 'D5',
                     '--sources', 'MISSING', 'S1', 'S1', 'S1', 'S1', '--why', 'Decision priority.')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual([p.read_bytes() for p in paths], before)

    def test_all_five_get_real_verdicts_and_other_leads_stay_on_card(self):
        self.draft()
        self.submit()
        self.verdicts()
        self.assertV2Clean()
        r = run_tool('card', self.w)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        card = (self.w / 'IDEA-CARD.md').read_text(encoding='utf-8')
        report = (self.w / 'IDEA-REPORT.md').read_text(encoding='utf-8')
        self.assertIn('5 submitted to VP', card)
        self.assertIn('5 verdicts', card)
        self.assertIn('9 distinct leads', card)
        for q in LEADS[5:]:
            line = next(l for l in card.splitlines() if q in l)
            self.assertIn('unverified (memory)', line)
        for q in LEADS:
            self.assertIn(q, report)
        self.assertLessEqual(len(card.splitlines()), 80)

    def test_negative_verdicts_mark_leads_without_deleting_them(self):
        self.draft()
        self.submit()
        self.verdicts('ABSENT')
        self.assertV2Clean()
        r = run_tool('card', self.w)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        report = (self.w / 'IDEA-REPORT.md').read_text(encoding='utf-8')
        self.assertIn('ABSENT', report)
        self.assertEqual(load_tool('hybrid').richness(self.w)['leads'], 9)
        self.assertNotIn('or removed', load_tool('hybrid').richness_line(load_tool('hybrid').richness(self.w)))

    def test_tampered_submission_and_mismatched_verdict_are_errors(self):
        self.draft()
        d = self.submit()
        cid = d['claims'][0]['verification']['claim']
        self.verdicts()
        vp = self.fx / 'vp_prior_art'
        mutate(vp, 'verdicts.json', lambda v: [x.update(text='Different proposition.')
                                            for x in v['claims'] if x['id'] == cid])
        self.assertBlocks('[DRAFT-SUBMISSION]')
        mutate(vp, 'card.json', lambda v: [x.update(text='Different proposition.')
                                         for x in v['claims'] if x['id'] == cid])
        self.assertBlocks('[DRAFT-SUBMISSION]')

    def test_four_claims_still_select_all_and_missing_verdicts_are_marks(self):
        self.draft(4)
        self.assertMarks('[DRAFT-PRIORITY]')
        self.submit(['D1', 'D2', 'D3', 'D4'])
        self.verdicts()
        self.assertV2Clean()


    # Terra review of round 2 (orchestrator fixes)
    def test_under_inventory_cannot_shrink_the_required_selection(self):
        self.draft()
        mutate(self.w, 'draft_claims.json', lambda d: d.update(claims=d['claims'][:1]))
        self.assertMarks('[DRAFT-INVENTORY]')
        r = run_tool('hybrid', 'submit', self.w, '--run', 'prior_art', '--claims', 'D1',
                     '--sources', 'S1', '--why', 'Decision priority.')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('inventory incomplete', r.stdout + r.stderr)

    def test_submitted_open_leads_stay_visible_on_card_with_status(self):
        self.draft()
        self.submit()
        r = run_tool('card', self.w)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        card = (self.w / 'IDEA-CARD.md').read_text(encoding='utf-8')
        for q in LEADS[:5]:
            self.assertIn('no verdict yet', next(l for l in card.splitlines() if q in l))
        self.verdicts('ABSENT')
        run_tool('card', self.w)
        card = (self.w / 'IDEA-CARD.md').read_text(encoding='utf-8')
        report = (self.w / 'IDEA-REPORT.md').read_text(encoding='utf-8')
        for q in LEADS[:5]:
            self.assertIn('VP: ABSENT', next(l for l in card.splitlines() if q in l))
        self.assertIn('verdicts.json claim', report)
        self.assertLessEqual(len(card.splitlines()), 80)

    def test_historical_richness_wording_outside_v2(self):
        hy = load_tool('hybrid')
        r = {'claims': 3, 'leads': 2, 'magnitudes': 1, 'verified': 1, 'verified_share': 0.333}
        self.assertIn('or removed', hy.richness_line(dict(r, v2=False)))
        self.assertNotIn('or removed', hy.richness_line(dict(r, v2=True)))


class CardPageTest(V2):
    def setUp(self):
        super().setUp()
        self.w = self.to_v2(REBOUND)
        for name in ('rebound.json', 'rebound_after.json'):
            mutate(self.w, name, lambda d: [i.update(search_plan=plan_of(i['id'], i['prior_art']['queries']))
                                           for i in d['ideas']])
        mutate(self.w, 'rebound_after.json', lambda d: d.update(outcome_source='scenario'))

    def render(self, cap=80):
        mod = load_tool('card')
        cfg = mod.common.config()
        cfg['card_max_lines'] = cap
        # The obsolete v2 override must not supersede card_max_lines.
        cfg['card_max_lines_v2'] = 110
        with patch.object(mod.common, 'config', return_value=cfg):
            card = mod.render(self.w)
            report = mod.render(self.w, full=True)
            problems = mod.check.card_text_problems(self.w, card)
            too_long = mod.check.card_text_problems(self.w, card + '\n' * (cap + 1))
        self.assertEqual(problems, [], problems)
        self.assertTrue(any(p.startswith('[CARD]') for p in too_long))
        return card, report

    def test_neighbours_and_conditional_ideas_are_one_whole_line_each(self):
        card, report = self.render()
        for name in ('rebound.json', 'rebound_after.json'):
            for idea in read_json(self.w / name)['ideas']:
                line = next(l for l in card.splitlines() if l.startswith('- ' + idea['id'] + ' '))
                for val in (idea['operator'], idea['statement'], idea['prior_art']['status']):
                    self.assertIn(val, line)
        self.assertIn('Scenarios, no result yet', card)
        self.assertNotIn('idea(s): the list is in', card)
        self.assertLessEqual(len(card.splitlines()), 80)

    def test_conclusions_thresholds_actions_scenarios_stay_whole_at_configured_cap(self):
        card, report = self.render(72)
        self.assertLessEqual(len(card.splitlines()), 72)
        self.assertNotRegex(card, r'…|\.\.\.|\(\+\d+ more')
        reco = read_json(self.w / 'recommendation.json')
        self.assertIn(reco['reason'], card)
        self.assertIn(reco['next_step']['first_action'], card)
        tests = read_json(self.w / 'tests.json')
        for t in tests['tests']:
            for key in ('continue_if', 'revise_if', 'stop_if', 'indeterminate_if'):
                self.assertIn(t['decision_rule'][key].rstrip('.'), card)
        for data in (tests, read_json(self.w / 'rebound.json'), read_json(self.w / 'rebound_after.json')):
            for s in data['ranking']['scenarios']:
                line = next(l for l in card.splitlines() if s['if'].rstrip('.') in l)
                self.assertIn(s['then'].rstrip('.'), line)

    def test_detail_moves_to_report_with_explicit_pointers(self):
        card, report = self.render()
        self.assertNotIn('- Iteration 1:', card)
        self.assertIn('- Iteration 1:', report)
        self.assertNotIn('Coverage (observable, from the VP gateway journal)', card)
        self.assertIn('Coverage (observable, from the VP gateway journal)', report)
        for c in read_json(self.w / 'decisive_claims.json')['claims']:
            line = next(l for l in card.splitlines() if 'Decisive evidence ' + c['id'] in l)
            self.assertNotIn('; scope:', line)
            self.assertIn('IDEA-REPORT.md', line)
            self.assertIn(c['scope'], report)
            self.assertIn(c['limits'], report)
        self.assertIn('recall unknown', card)


class EvidenceAndDocsTest(V2):
    def test_available_v2_card_and_supplied_replay_preserve_evidence(self):
        root = FRONTIER / 'tests' / 'fixtures' / 'synthetic_packing_run'
        # IDEA-CARD-v2-1.md is not supplied. Use the committed legacy V2 card,
        # without inventing the unavailable historical oversize-card evidence.
        text = (FRONTIER / 'tests' / 'fixtures' / 'synthetic-legacy-v2-card.md').read_text(encoding='utf-8')
        self.assertIn('Title length and citation counts across fields', text)
        self.assertIn('differs: Observational association only', text)
        self.assertIn('Power at minimum useful effect', text)
        self.assertLessEqual(len(text.splitlines()), 80)
        # V5 pins the synthetic packing card in the fixture; the older loose
        # replay file is absent. No missing historical evidence is reconstructed.
        replay = (root / 'IDEA-CARD.md').read_text(encoding='utf-8')
        self.assertIn('0% of the claims verified', replay)
        self.assertLessEqual(len(replay.splitlines()), 80)
        for iid in ('N1', 'N2', 'N3', 'N4', 'N5', 'B1', 'B2'):
            self.assertRegex(replay, r'(?m)^- %s ' % iid)

    def test_host_obligations_and_one_page_limit_are_documented(self):
        text = (FRONTIER / 'SKILL.md').read_text(encoding='utf-8')
        for phrase in ('MUST select the five', 'hybrid.py submit', '[DRAFT-NOSUBMIT]',
                       '[DRAFT-VERDICT]', 'card_max_lines', 'one line per idea'):
            self.assertIn(phrase, text)
        self.assertNotIn('110 lines in v2', text)
