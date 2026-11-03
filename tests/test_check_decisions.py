#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of check_decisions.py: extraction of French court citations (prose, JSON objects inside a text, JSON input), the statuses
found / mismatch / not_found / not_checked against a fake gateway built from recorded-shape Judilibre records (tests/fixtures/
check_decisions_judilibre.json: numbers and dates as observed, texts shortened), the quoted-fragment support check, the real gateway without PISTE credentials
(0 request, not_checked), and the command line. No network, no model."""
import json, os, pathlib, subprocess, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent
TOOL = P.parent / 'tools' / 'check_decisions.py'
sys.path.insert(0, str(P.parent / 'tools')); import check_decisions as C   # noqa: E702
FIX = json.loads((P / 'fixtures' / 'check_decisions_judilibre.json').read_text(encoding='utf-8'))


class FakeGateway:
    """Judilibre as the gateway serves it: search by number (court filter, date window), read by id; every call recorded."""
    def __init__(self, records=None, skipped=None):
        self.records = FIX['records'] if records is None else records; self.skipped = skipped; self.calls = []

    def call(self, cmd, arg, n=20, **opt):
        self.calls.append((cmd, arg, opt))
        if self.skipped: return {'results': {'status': 'skipped', 'reason': self.skipped, 'refusal': self.skipped + ': x'}, 'excluded_post_T_or_forbidden': 0}
        if cmd == 'read':
            r = next((x for x in self.records if x['id'] == arg), None)
            return {'results': dict(r, abstract=r['text'], text_source='Judilibre (pseudonymised official text, whole)') if r else {'refusal': 'not found'}}
        court = opt.get('court') or 'cc'
        out = [r for r in self.records if r['court'] == court and (arg in r['numbers'] or arg.upper() == (r.get('ecli') or ''))
               and (not opt.get('date_from') or opt['date_from'] <= r['date'] <= opt['date_to'])]
        return {'results': out[:n], 'excluded_post_T_or_forbidden': 0}


def by_number(rep): return {c['number']: c for c in rep['citations']}


class Extraction(unittest.TestCase):
    def test_prose_forms(self):
        t = ("La chambre sociale l'a jugé (Cass. soc., 18 mars 2026, n° 24-15.143). Voir aussi Cass. com., 6 mai 2026, pourvoi n° F 25-12493. "
             "La cour d'appel de Lyon, 19 mars 2026, RG n° 24/07526, a suivi. Cass. 1re civ., 11/03/2026, n° 24-17.058. "
             "Enfin ECLI:FR:CCASS:2026:SO00225.")
        c = by_number({'citations': C.extract(t)})
        self.assertEqual(set(c), {'24-15.143', '25-12.493', '24/07526', '24-17.058', 'ECLI:FR:CCASS:2026:SO00225'})
        self.assertEqual((c['24-15.143']['court'], c['24-15.143']['chamber'], c['24-15.143']['date']), ('cc', 'soc', '2026-03-18'))
        self.assertEqual((c['25-12.493']['chamber'], c['25-12.493']['date']), ('comm', '2026-05-06'))
        self.assertEqual((c['24/07526']['kind'], c['24/07526']['court'], c['24/07526']['city'], c['24/07526']['date']), ('docket', 'ca', 'Lyon', '2026-03-19'))
        self.assertEqual((c['24-17.058']['chamber'], c['24-17.058']['date']), ('civ1', '2026-03-11'))
        self.assertEqual(c['ECLI:FR:CCASS:2026:SO00225']['kind'], 'ecli')
        e = by_number({'citations': C.extract("La cour d'appel de Metz, puis ECLI:FR:CCASS:2026:C100170.")})['ECLI:FR:CCASS:2026:C100170']
        self.assertEqual((e['court'], e['city']), ('cc', None))
        self.assertIn('chambre sociale', c['24-15.143']['claim'])

    def test_dates_are_not_numbers_and_shared_citation(self):
        t = "Le 2026-03-18 et le 18/03/2026 ne sont pas des pourvois. Cass. soc., 6 mai 2026 (24-10.699 ou 25-12.493). Puis CA Bordeaux, 3 mars 2026, RG 23/05022."
        c = by_number({'citations': C.extract(t)})
        self.assertEqual(set(c), {'24-10.699', '25-12.493', '23/05022'})
        self.assertEqual((c['25-12.493']['date'], c['25-12.493']['chamber']), ('2026-05-06', 'soc'))     # "X ou Y": Y shares X's court and date
        self.assertEqual((c['23/05022']['city'], c['23/05022']['date']), ('Bordeaux', '2026-03-03'))

    def test_appeal_number_stays_cassation(self):
        t = "Cass. soc., 8 juillet 2026, n° 24-22.147 : cassation d'un arrêt de la cour d'appel de Bordeaux. Puis l'arrêt n° 25-15.008 de la cour d'appel de Bourges."
        c = by_number({'citations': C.extract(t)})
        self.assertEqual((c['24-22.147']['court'], c['24-22.147']['chamber'], c['24-22.147']['city']), ('cc', 'soc', None))
        self.assertEqual((c['25-15.008']['kind'], c['25-15.008']['court']), ('appeal', 'cc'))
        t2 = "Retour au droit commun de la durée du travail. Dans l'arrêt du 9 avril 2026 (pourvoi n° 24-21.017), la Cour de cassation juge..."
        self.assertIsNone(C.extract(t2)[0]['chamber'])                       # 'commun' is not the chambre commerciale

    def test_json_objects_in_text_and_json_input(self):
        blk = {'solution': 's', 'decisions': [{'juridiction': 'Cour de cassation, chambre sociale', 'date': '2026-03-18', 'numero': '24-15.143',
                                               'apport': 'Rejet : « ne suffit pas à caractériser un préjudice indemnisable ».'},
                                              {'juridiction': "Cour d'appel de Lyon", 'date': '2026-03-19', 'numero': '24/07526', 'apport': 'x'}]}
        t = 'Texte libre.\n<reponse>' + json.dumps(blk, ensure_ascii=False) + '</reponse>'
        c = by_number({'citations': C.extract(t)})
        self.assertEqual(c['24-15.143']['origin'], 'text_json')
        self.assertIn('préjudice', c['24-15.143']['claim'])
        self.assertEqual((c['24/07526']['court'], c['24/07526']['city']), ('ca', 'Lyon'))
        j = by_number({'citations': C.extract_json(blk)})
        self.assertEqual(set(j), {'24-15.143', '24/07526'})
        self.assertEqual(by_number({'citations': C.extract_json([{'numero': '2415143', 'date': '18 mars 2026'}])})['24-15.143']['date'], '2026-03-18')

    def test_duplicates_merged(self):
        t = 'Cass. soc., 18 mars 2026, n° 24-15.143. Plus loin : Cass. soc., 18 mars 2026, n° 24-15.143.'
        cs = C.extract(t)
        self.assertEqual((len(cs), cs[0]['occurrences']), (1, 2))


class Statuses(unittest.TestCase):
    def run_check(self, text, **k):
        gw = FakeGateway(**k); return C.check(C.extract(text), gateway=gw), gw

    def test_found_mismatch_not_found(self):
        t = ('Cass. soc., 18 mars 2026, n° 24-15.143. Cass. soc., 6 mai 2026, n° 25-12.493. Cass. soc., 9 avril 2026, n° 24-21.017. '
             'Cass. soc., 12 février 2026, n° 99-99.999.')
        rep, _ = self.run_check(t); c = by_number(rep)
        self.assertEqual(c['24-15.143']['status'], 'found')
        self.assertEqual((c['25-12.493']['status'], c['25-12.493']['differences']), ('mismatch', ['chamber']))   # real: chambre commerciale
        self.assertEqual((c['24-21.017']['status'], c['24-21.017']['differences']), ('mismatch', ['date']))
        self.assertEqual(c['24-21.017']['match']['date'], '2026-04-10')
        self.assertEqual((c['99-99.999']['status'], c['99-99.999'].get('coverage')), ('not_found', None))
        self.assertEqual(rep['summary'], {'found': 1, 'mismatch': 2, 'not_found': 1, 'not_checked': 0})
        self.assertEqual(C.exit_code(rep), 1)

    def test_docket_numbers_are_per_court(self):
        t = ("CA Paris, 27 février 2026, RG 24/07526. Cour d'appel de Lyon, 19 mars 2026, RG 24/07526. CA Metz, 9 avril 2026, RG 24/00119.")
        rep, gw = self.run_check(t)
        c = {(x['city'], x['number']): x for x in rep['citations']}
        self.assertEqual(c[('Paris', '24/07526')]['status'], 'found')
        lyon = c[('Lyon', '24/07526')]
        self.assertEqual((lyon['status'], lyon['coverage']), ('not_found', 'partial'))
        self.assertEqual(lyon['same_number_elsewhere'][0]['location'], 'ca_paris')
        self.assertEqual(c[('Metz', '24/00119')]['status'], 'found')
        self.assertIn(('search-judilibre', '24/00119', {'date_from': '2026-04-09', 'date_to': '2026-04-09', 'court': 'ca'}), gw.calls)

    def test_ecli(self):
        rep, _ = self.run_check('Voir ECLI:FR:CCASS:2026:SO00225, rendu le 18 mars 2026.')
        self.assertEqual(rep['citations'][0]['status'], 'found')

    def test_skipped_engine_is_not_checked(self):
        rep, _ = self.run_check('Cass. soc., 18 mars 2026, n° 24-15.143.', skipped='not_configured')
        self.assertEqual((rep['citations'][0]['status'], rep['citations'][0]['why']), ('not_checked', 'judilibre_not_configured'))
        self.assertEqual(C.exit_code(rep), 0); self.assertEqual(C.exit_code(rep, strict=True), 1)

    def test_cap_and_error_are_not_checked(self):
        class Cap:
            def call(self, *a, **k): return {'refusal': 'CAP reached (150 calls of the check_decisions budget)'}
        class Err:
            def call(self, *a, **k): return {'results': {'error': 'ProviderError: PISTE HTTP 503'}}
        cs = C.extract('Cass. soc., 18 mars 2026, n° 24-15.143.')
        self.assertEqual(C.check(cs, gateway=Cap())['citations'][0]['why'], 'cap_reached')
        self.assertTrue(C.check(cs, gateway=Err())['citations'][0]['why'].startswith('provider_error'))
        self.assertEqual(C.check(cs, offline=True)['citations'][0]['why'], 'offline')

    def test_support_fragments(self):
        t = ('Cass. soc., 18 mars 2026, n° 24-15.143 : « la seule absence de tenue des entretiens sur la charge de travail ne suffit pas ». '
             'Cass. soc., 11 mars 2026, n° 24-22.163 : « le forfait est nul de plein droit ». Cass. soc., 1er juillet 2026, n° 25-10.960, sans citation.')
        rep = C.check(C.extract(t), gateway=FakeGateway(), support_check=True); c = by_number(rep)
        self.assertEqual(c['24-15.143']['support']['status'], 'supported')
        self.assertEqual(c['24-22.163']['support']['status'], 'not_supported')
        self.assertEqual((c['25-10.960']['support']['status'], c['25-10.960']['support']['why']), ('undetermined', 'no_quoted_fragment'))
        self.assertIsNotNone(c['25-10.960']['support']['word_overlap'])

    def test_real_gateway_without_credentials_sends_nothing(self):
        with tempfile.TemporaryDirectory() as t:
            f = pathlib.Path(t) / 'a.txt'; f.write_text('Cass. soc., 18 mars 2026, n° 24-15.143.', encoding='utf-8')
            env = {k: v for k, v in os.environ.items() if not k.startswith('PISTE_')}; env['HOME'] = t
            r = subprocess.run([sys.executable, '-I', str(TOOL), str(f), '--T', '2026-11-03', '--state', str(pathlib.Path(t) / 'st')],
                               capture_output=True, text=True, env=env, cwd=t)
            self.assertEqual(r.returncode, 0, r.stderr)
            c = json.loads(r.stdout)['citations'][0]
            self.assertEqual((c['status'], c['why']), ('not_checked', 'judilibre_not_configured'))
            self.assertFalse((pathlib.Path(t) / 'st' / 'requests.jsonl').exists())          # 0 request

    def test_command_line(self):
        with tempfile.TemporaryDirectory() as t:
            f = pathlib.Path(t) / 'c.json'; f.write_text(json.dumps({'decisions': [{'juridiction': 'Cass. soc.', 'date': '2026-03-18', 'numero': '24-15.143'}]}))
            r = subprocess.run([sys.executable, '-I', str(TOOL), str(f), '--offline'], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)['summary']['not_checked'], 1)
            r = subprocess.run([sys.executable, '-I', str(TOOL), str(f), '--T', '3/11/2026'], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)
            r = subprocess.run([sys.executable, '-I', str(TOOL), str(pathlib.Path(t) / 'absent.txt')], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)

    def test_no_machine_path_nor_model_name(self):
        src = TOOL.read_text(encoding='utf-8')
        for bad in ('/root', '/docker', '/home/', 'sonnet', 'opus', 'claude-', 'gpt-'):
            self.assertNotIn(bad, src)


if __name__ == '__main__':
    unittest.main()
