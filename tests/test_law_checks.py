#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of law_checks.py (plugins/law.md, "Verification rules"): the real examples of the plugin (dates copied from Cellar and from
the administrative open data), the mapping to level-1 statuses on a run directory, the command line, and a mutation set: every mutant of the
rule code is caught by at least one case while the unmodified code (control) passes them all. No network, no model."""
import json, os, pathlib, subprocess, sys, tempfile, types, unittest
P = pathlib.Path(__file__).resolve().parent
TOOL = P.parent / 'tools' / 'law_checks.py'
sys.path.insert(0, str(P.parent / 'tools')); import law_checks as L   # noqa: E702
SRC = TOOL.read_text(encoding='utf-8')


def eq(a, b, what=''):
    if a != b: raise AssertionError(f'{what}: {a!r} != {b!r}')


def A(key, ident, origin='record', refusal=None, **rec): return {'key': key, 'ident': ident, 'rec': rec, 'origin': origin, 'refusal': refusal, 'error': None}


def ctx(as_of, order='EU', T='2026-10-28', today='2026-10-22', **k): return dict({'as_of': L.day(as_of), 'order': order, 'T': L.day(T), 'today': L.day(today), 'comparative': False}, **k)


def leg(celex, **f): return A('S-' + celex, 'celex:' + celex, **dict({'celex': celex, 'type': 'text', 'tier': 'primary', 'order': 'EU', 'declared_void_by': []}, **f))


# Real records (Cellar, 2026-10-22/28): directive 95/46 in force until 2018-05-24 inclusive; GDPR in force 2016-05-24, applicable 2018-05-25.
DIR_95_46 = dict(in_force_from='1995-12-13', applies_from='1995-12-13', in_force_to='2018-05-24', in_force='0')
GDPR = dict(in_force_from='2016-05-24', applies_from='2018-05-25', in_force_to='9999-12-31', in_force='1')
INTEL_GC = A('S3', 'celex:62009TJ0286', celex='62009TJ0286', type='decision', court='TJ', date='2014-06-12', tier='primary', order='EU',
             set_aside_by=['62014CJ0413'], declared_void_by=[{'celex': '62014CJ0413', 'date': '2017-09-06', 'by_preliminary_ruling': False}])
INTEL_CJ = A('S4', 'celex:62014CJ0413', celex='62014CJ0413', type='decision', court='CJ', date='2017-09-06', tier='primary', order='EU', set_aside_by=[], declared_void_by=[])
CE_473547 = A('S5', 'ja:CE/DCE_473547_20230524', type='decision', court='CE', date='2023-05-24', tier='primary', order='FR-ADM', coverage_from='2021-09-30')
TA = A('S6', 'ja:TA75/DTA_2320429_20261019', type='decision', court='TA75', date='2026-10-19', tier='primary', order='FR-ADM', coverage_from='2022-06-30')
HUDOC = A('S7', 'ecli:ECLI:CE:ECHR:2024:0409JUD005360020', type='decision', date='2024-04-09', tier='primary', order='COE')
HAL = A('S8', 'hal:hal-05523091', type='ART', tier='secondary', order=None, date='2024-06-01')
THESIS = A('S9', 'thesesfr:2019PA020001', type='thesis', tier='secondary', order=None, date='2019-01-18')


def res(M, anchors, as_of, claim=None, **k):
    o = M.check_claim(claim or {'id': 'A1', 'text': 'x'}, anchors, ctx(as_of, **k))
    return min((x['result'] for x in o), key=M.RANK.get, default='supported'), o


def rule(o, name): return [x for x in o if x['rule'] == name]


# ---------------------------------------------------------------- cases (each takes the module under test: real or mutant)

def case_95_46_inclusive_end(M):
    eq(res(M, [leg('31995L0046', **DIR_95_46)], '2018-03-01')[0], 'supported', 'before repeal')
    eq(res(M, [leg('31995L0046', **DIR_95_46)], '2018-05-24')[0], 'supported', 'last day, inclusive')
    r, o = res(M, [leg('31995L0046', **DIR_95_46)], '2018-05-25')
    eq(r, 'unsupported', 'day after'); eq(rule(o, 'in_force_at_date')[0]['bias'], 'law.not_in_force')
    eq(M.law_status(o)[0], 'DISTORTED', 'not in force maps to DISTORTED')


def case_gdpr_applies_from(M):
    eq(res(M, [leg('32016R0679', **GDPR)], '2018-03-01')[0], 'needs_confirmation', 'in force, not yet applicable')
    eq(res(M, [leg('32016R0679', **GDPR)], '2018-06-01')[0], 'supported', 'applicable')
    eq(res(M, [leg('32016R0679', **GDPR)], '2015-01-01')[0], 'unsupported', 'not yet in force')


def case_open_end_sentinels(M):
    for s in ('9999-12-31', '2999-01-01'):
        eq(res(M, [leg('32020R0001', in_force_from='2020-01-01', applies_from='2020-01-01', in_force_to=s)], '2026-10-01')[0], 'supported', s)


def case_exclusive_end_legi(M):   # LEGI: [valid_from, valid_until)
    old = A('L1', None, valid_from='1804-02-17', valid_until='2016-10-01', tier='primary', order='FR', type='text', version='LEGIARTI000006436298', declared_void_by=[])
    new = A('L2', None, valid_from='2016-10-01', valid_until='2999-01-01', tier='primary', order='FR', type='text', version='LEGIARTI000032040794', declared_void_by=[])
    eq(res(M, [old], '2016-09-30', order='FR')[0], 'supported', 'old on its last day')
    eq(res(M, [old], '2016-10-01', order='FR')[0], 'unsupported', 'old on the first day of the next version')
    eq(res(M, [new], '2016-10-01', order='FR')[0], 'supported', 'new from its first day')
    eq(res(M, [new], '2016-09-30', order='FR')[0], 'unsupported', 'new the day before')


def case_flag_contradicting_dates(M):   # Cellar OPTIONAL-on-ELI trap: 95/46 served with the dates of decision 2021/701 and its own flag 0
    r, o = res(M, [leg('31995L0046', in_force_from='2021-07-02', applies_from='2021-07-02', in_force_to='9999-12-31', in_force='0')], '2022-03-01')
    eq(r, 'needs_confirmation', 'flag vs dates'); eq('inconsistent' in rule(o, 'in_force_at_date')[0]['trigger'], True, 'trigger')
    eq(res(M, [leg('32016R0679', **dict(GDPR, in_force='0'))], '2018-06-01')[0], 'needs_confirmation', 'GDPR flag 0')
    eq(res(M, [leg('32016R0679', **dict(GDPR, in_force='true'))], '2018-06-01')[0], 'supported', 'flag consistent')


def case_missing_or_bad_dates(M):
    eq(res(M, [leg('31995L0046', **DIR_95_46)], None)[0], 'needs_confirmation', 'no question date')
    eq(res(M, [leg('31995L0046', applies_from='1995-12-13', in_force_to='2018-05-24')], '2018-03-01')[0], 'needs_confirmation', 'no start')
    eq(res(M, [leg('31995L0046', in_force_from='13/12/1995', in_force_to='2018-05-24')], '2018-03-01')[0], 'needs_confirmation', 'bad start')
    eq(res(M, [leg('31995L0046', in_force_from='1995-12-13', applies_from='1995-12-13')], '2018-03-01')[0], 'needs_confirmation', 'end unknown')


def case_masked_validity_under_T(M):   # gateway, notice modified on/after T: end and flag masked; T 2018-03-01
    m = dict(in_force_from='1995-12-13', applies_from='1995-12-13', in_force_to=None, in_force=None, validity='notice modified on/after T: post-T validity masked')
    eq(res(M, [leg('31995L0046', **m)], '2018-01-15', T='2018-03-01')[0], 'supported', 'no end before T')
    eq(res(M, [leg('31995L0046', **m)], '2018-03-01', T='2018-03-01')[0], 'supported', 'question date = T, inclusive end on/after T')
    eq(res(M, [A('L9', None, type='text', tier='primary', order='FR', valid_from='2000-01-01', applies_from='2000-01-01', valid_until=None, validity='masked', version='x', declared_void_by=[])],
               '2018-03-01', T='2018-03-01', order='FR')[0], 'needs_confirmation', 'exclusive end masked on T')
    g = dict(in_force_from='2016-05-24', applies_from=None, in_force_to=None, in_force=None, validity='masked')
    eq(res(M, [leg('32016R0679', **g)], '2018-01-15', T='2018-03-01')[0], 'needs_confirmation', 'application masked (on/after T)')


def case_void_from_outset(M):   # directive 2006/24: end = entry into force, declared void by C-293/12 (preliminary ruling)
    r, o = res(M, [leg('32006L0024', in_force_from='2006-05-03', applies_from='2006-05-03', in_force_to='2006-05-03', in_force='0',
                       declared_void_by=[{'celex': '62012CJ0293', 'date': '2014-04-08', 'by_preliminary_ruling': True}])], '2015-01-01')
    eq(r, 'unsupported', '2006/24'); eq({x['rule'] for x in o if x['result'] == 'unsupported'}, {'in_force_at_date', 'not_overturned'}, 'both rules')


def case_intel_set_aside(M):
    r, o = res(M, [INTEL_GC], '2020-01-01')
    eq(r, 'unsupported', 'T-286/09'); eq('62014CJ0413' in rule(o, 'not_overturned')[0]['trigger'], True, 'names C-413/14 P')
    eq(M.law_status(o)[0], 'DISTORTED', 'overruled maps to DISTORTED')
    eq(res(M, [INTEL_CJ], '2020-01-01')[0], 'supported', 'C-413/14 P, last resort')
    eq(res(M, [INTEL_CJ], '2016-01-01')[0], 'unsupported', 'ruling later than the question date')
    eq(res(M, [INTEL_GC], '2016-01-01')[0], 'supported', 'set aside only on 2017-09-06, after the question date')


def case_lower_court_without_history(M):
    eq(res(M, [TA], '2026-10-20', order='FR')[0], 'needs_confirmation', 'TA')
    eq(res(M, [CE_473547], '2023-06-01', order='FR')[0], 'supported', 'CE')
    eq(res(M, [HUDOC], '2024-05-01', order='COE')[0], 'needs_confirmation', 'HUDOC without history')


def case_klimaseniorinnen_doctrine_only(M):
    r, o = res(M, [HAL, THESIS], '2025-01-01', order='COE')
    eq(r, 'needs_confirmation', 'doctrine only'); eq(rule(o, 'source_tier')[0]['bias'], 'law.doctrine_for_primary', 'bias')
    eq(res(M, [CE_473547, HAL], '2023-06-01', order='FR')[0], 'supported', 'doctrine next to a primary source')
    eq(res(M, [HAL], '2025-01-01', claim={'id': 'A1', 'text': 'x', 'decisive': False}, order='FR')[0], 'supported', 'not decisive')
    eq(res(M, [A('S0', None, origin='card', type='text')], '2025-01-01', order='FR')[1][-1]['result'], 'needs_confirmation', 'tier unknown')


def case_jurisdiction(M):
    eq(res(M, [leg('31995L0046', **DIR_95_46)], '2018-03-01', order='FR')[0], 'needs_confirmation', 'EU source, FR question')
    eq(rule(res(M, [HUDOC], '2024-05-01', order='FR')[1], 'jurisdiction_match')[0]['result'], 'needs_confirmation', 'COE for FR')
    r, o = res(M, [CE_473547], '2023-06-01', order='EU')
    eq(r, 'unsupported', 'CE 473547 for an EU question'); eq(M.law_status(o)[0], 'ABSENT', 'foreign order maps to ABSENT')
    eq(rule(res(M, [A('S9', None, date='2024-01-01', type='decision', tier='primary', order='FR-JUD', court='cc')], '2024-02-01', order='FR-ADM')[1], 'jurisdiction_match')[0]['result'],
       'needs_confirmation', 'other French order')
    eq(rule(res(M, [CE_473547], '2023-06-01', order='EU', comparative=True)[1], 'jurisdiction_match')[0]['result'], 'supported', 'comparative')
    eq(rule(res(M, [CE_473547], '2023-06-01', order=None)[1], 'jurisdiction_match')[0]['result'], 'needs_confirmation', 'order unknown')
    eq(rule(res(M, [A('S2', None, date='2024-01-01', type='decision', tier='primary', order='undefined', court='CE')], '2024-02-01', order='FR')[1],
            'jurisdiction_match')[0]['result'], 'needs_confirmation', 'null literal = unknown order')
    eq(rule(res(M, [HAL], '2025-01-01', order='EU')[1], 'jurisdiction_match'), [], 'doctrine exempt')


def case_official_text(M):
    r, o = res(M, [A('S1', 'celex:62014CJ0413_RES', celex='62014CJ0413_RES', type='decision', court='CJ', date='2017-09-06', tier='primary', order='EU', set_aside_by=[])], '2020-01-01')
    eq(r, 'unsupported', '_RES'); eq(M.law_status(o)[0], 'SOURCE-UNAVAILABLE', '_RES maps to SOURCE-UNAVAILABLE')
    eq(rule(res(M, [A('S1', 'celex:62012CC0293', celex='62012CC0293', type='decision', date='2013-12-12', tier='primary', order='EU')], '2020-01-01')[1], 'official_text')[0]['bias'],
       'law.non_binding', 'AG opinion')
    eq(rule(res(M, [INTEL_CJ], '2020-01-01')[1], 'official_text'), [], 'judgment is official')


def case_resolves(M):
    r, o = res(M, [A('S1', 'celex:32016R9999', origin='none', refusal='not found')], '2020-01-01')
    eq(rule(o, 'resolves')[0]['result'], 'unsupported', 'not found'); eq(M.law_status(o)[0], 'ABSENT', 'fabricated -> ABSENT')
    eq(rule(res(M, [A('S1', 'celex:2016-679', origin='card')], '2020-01-01')[1], 'resolves')[0]['result'], 'unsupported', 'malformed CELEX')
    eq(rule(res(M, [A('S1', 'celex:32016R0679', origin='card', type='text', tier='primary', order='EU')], '2020-01-01')[1], 'resolves')[0]['result'],
       'needs_confirmation', 'offline, no record')
    eq(rule(M.check_claim({'id': 'A1'}, [A('S1', 'celex:32016R0679', origin='none')], dict(ctx('2020-01-01'), verifier_discrepancy='not found')), 'resolves')[0]['result'],
       'unsupported', 'verifier read: not found')
    eq(rule(res(M, [leg('32016R0679', **GDPR)], '2018-06-01')[1], 'resolves')[0]['result'], 'supported', 'record read')


def case_versions(M):
    eq(rule(res(M, [leg('02016R0679-20160504', **GDPR)], '2018-06-01')[1], 'version_pinned')[0]['result'], 'supported', 'consolidated before')
    eq(rule(res(M, [leg('02016R0679-20190101', **GDPR)], '2018-06-01')[1], 'version_pinned')[0]['result'], 'unsupported', 'consolidated after')
    eq(rule(res(M, [leg('02016R0679', **GDPR)], '2018-06-01')[1], 'version_pinned')[0]['result'], 'needs_confirmation', 'no version date')
    dead = A('L3', None, valid_from='2016-10-01', valid_until='2999-01-01', legi_state='MODIFIE_MORT_NE', tier='primary', order='FR', type='text', version='x', declared_void_by=[])
    eq(res(M, [dead], '2017-01-01', order='FR')[0], 'unsupported', 'MODIFIE_MORT_NE')


def case_negative_coverage(M):
    c = {'id': 'A1', 'text': "No decision of the Conseil d'Etat applied the rule", 'negative': True, 'receipt': '"reconnaissance faciale"', 'window_from': '2019-01-01'}
    eq(rule(res(M, [CE_473547], '2023-06-01', claim=c, order='FR')[1], 'coverage')[0]['result'], 'needs_confirmation', 'before coverage')
    eq(rule(res(M, [CE_473547], '2023-06-01', claim=dict(c, window_from='2022-01-01'), order='FR')[1], 'coverage')[0]['result'], 'supported', 'within coverage')
    eq(rule(res(M, [CE_473547], '2023-06-01', claim=dict(c, window_from='2022-01-01', receipt='facial recognition'), order='FR')[1], 'coverage')[0]['result'],
       'needs_confirmation', 'no receipt by number or exact phrase')
    eq(rule(res(M, [HUDOC], '2024-05-01', claim=dict(c, window_from='2022-01-01'), order='COE')[1], 'coverage')[0]['result'], 'needs_confirmation', 'HUDOC')


def case_bounded_total(M):
    c = {'id': 'A1', 'text': 'All 1,000 decisions on the subject were annulled.', 'total': True}
    r, o = res(M, [CE_473547], '2023-06-01', claim=c, order='FR')
    eq(rule(o, 'bounded_total')[0]['result'], 'unsupported', 'complete'); eq(M.law_status(o)[0], 'DISTORTED', 'false total -> DISTORTED')
    eq(rule(res(M, [CE_473547], '2023-06-01', claim=dict(c, text='At least 1,000 decisions'), order='FR')[1], 'bounded_total')[0]['result'], 'supported', 'lower bound')


# ---------------------------------------------------------------- run directory (card + verdicts + sources) and command line

def make_run(d, claims, sources, verdicts, records=None, scope=None, card_extra=None):
    d = pathlib.Path(d); (d / 'sources').mkdir(parents=True, exist_ok=True)
    (d / 'card.json').write_text(json.dumps(dict({'card_id': 'law', 'question': 'q?', 'sources': sources, 'claims': claims}, **(card_extra or {}))))
    (d / 'verdicts.json').write_text(json.dumps({'claims': [{'id': i, 'status': s, 'discrepancy': x} for i, s, x in verdicts]}))
    (d / 'REPORT.md').write_text('report')
    for k, (name, body) in (records or {}).items():
        (d / 'sources' / k).mkdir(exist_ok=True); (d / 'sources' / k / name).write_text(json.dumps(body))
    if scope: (d / 'scope.md').write_text(scope)
    return d


def env_rec(**r): return {'call': 1, 'results': r}


def case_run_mapping(M):
    with tempfile.TemporaryDirectory() as t:
        gdpr = env_rec(id='celex:32016R0679', celex='32016R0679', type='text', tier='primary', order='EU', declared_void_by=[], **GDPR)
        d = make_run(t, [{'id': 'A1', 'text': 'GDPR applies.', 'source': {'key': 'S1'}, 'location': 'record'},
                         {'id': 'A2', 'text': 'Directive 95/46 governs.', 'source': {'key': 'S2'}, 'location': 'record', 'as_of': '2019-01-01'},
                         {'id': 'A3', 'text': 'Regulation 2016/999 says.', 'source': {'key': 'S3'}, 'location': 'record'},
                         {'id': 'A4', 'text': 'Intel GC holds.', 'source': {'key': 'S4'}, 'location': 'record'},
                         {'id': 'A5', 'text': 'A paper says.', 'source': {'key': 'S5'}, 'location': 'abstract'}],
                     {'S1': {'celex': '32016R0679', 'title': 'GDPR'}, 'S2': {'celex': '31995L0046', 'title': 'Directive 95/46', 'in_force_to': '9999-12-31'},
                      'S3': {'celex': '32016R0999', 'title': 'x'}, 'S4': {'id': 'celex:62009TJ0286', 'title': 'Intel'}, 'S5': {'doi': '10.1/x', 'title': 'p'}},
                     [('A1', 'FOUND', ''), ('A2', 'FOUND', ''), ('A3', 'SOURCE-UNAVAILABLE', 'not found'), ('A4', 'ABSENT', 'nothing'), ('A5', 'FOUND', '')],
                     {'S1': ('record.json', gdpr),
                      'S2': ('source.txt', env_rec(id='celex:31995L0046', celex='31995L0046', type='text', tier='primary', order='EU', declared_void_by=[], **DIR_95_46)),
                      'S4': ('record.json', {'results': INTEL_GC['rec']})},
                     scope='# Scope\nQuestion date: 2018-03-01\nLegal order: EU\n')
        r = M.check_run(d, today='2026-10-22'); c = {x['id']: x for x in r['claims']}
        eq((r['as_of'], r['as_of_origin'], r['order']), ('2018-03-01', 'scope.md', 'EU'), 'context from scope.md')
        eq((c['A1']['final_status'], c['A1']['flagged'], c['A1']['changed']), ('FOUND', True, False), 'GDPR before application: kept, flagged')
        eq((c['A2']['final_status'], c['A2']['anchors'][0]['record_origin']), ('DISTORTED', 'source'), 'record wins over card; injected source.txt read')
        eq(c['A3']['final_status'], 'ABSENT', 'unresolved CELEX'); eq('law.fabricated_citation' in c['A3']['catalogue'], True, 'catalogue id')
        eq((c['A4']['final_status'], c['A4']['changed']), ('ABSENT', False), 'verifier ABSENT stays (stricter than DISTORTED)')
        eq(r['not_law'], ['A5'], 'non-law claim skipped'); eq(sorted(r['to_apply']), ['A2', 'A3'], 'to_apply'); eq('A1' in r['to_flag'], True, 'to_flag')
        eq((d / 'REPORT.md').read_text(), 'report', 'REPORT.md untouched')


def case_context_origins(M):
    with tempfile.TemporaryDirectory() as t:
        d = make_run(t, [{'id': 'A1', 'text': 'x', 'source': {'key': 'S1'}, 'location': 'r'}], {'S1': {'celex': '32016R0679'}}, [('A1', 'FOUND', '')])
        eq(M.check_run(d)['as_of_origin'], 'unknown', 'nothing given')
        eq(M.check_run(d, as_of='2018-06-01', order='eu')[('as_of_origin')], '--as-of', 'flag')
        (d / 'state').mkdir(); (d / 'state' / 'journal.jsonl').write_text(json.dumps({'T': '2019-06-01', 'call': 'read'}) + '\n')
        eq((M.check_run(d)['as_of'], M.check_run(d)['as_of_origin']), ('2019-06-01', 'T (journal or --T)'), 'journal T')
        (d / 'card.json').write_text(json.dumps({'card_id': 'c', 'question': 'q', 'as_of': '2017-01-01', 'order': 'FR', 'sources': {}, 'claims': []}))
        eq((M.check_run(d, as_of='2018-06-01')['as_of'], M.check_run(d)['order']), ('2017-01-01', 'FR'), 'card first')


CASES = [v for k, v in sorted(globals().items()) if k.startswith('case_')]

# ---------------------------------------------------------------- mutants: (name, old, new), each applied once to tools/law_checks.py
CONTROL = ('control_identity', "RESULTS = (", "RESULTS = (")
MUTANTS = [
    # ported from the lab battery (20 of 20 killed there)
    ('end_inclusive_as_exclusive', '(as_of > e if inc else as_of >= e)', '(as_of >= e if inc else as_of >= e)'),
    ('end_exclusive_as_inclusive', '(as_of > e if inc else as_of >= e)', '(as_of > e if inc else as_of > e)'),
    ('applies_from_ignored', '        if as_of < ap:', '        if False:'),
    ('missing_start_passes', "if start is None: return out('in_force_at_date', 'needs_confirmation'", "if start is None: return out('in_force_at_date', 'supported'"),
    ('bad_question_date_passes', "if as_of is None: return out('in_force_at_date', 'needs_confirmation'", "if as_of is None: return out('in_force_at_date', 'supported'"),
    ('any_court_final', 'court in FINAL_COURTS', 'court'),
    ('history_value_ignored', "    if by: return out('not_overturned'", "    if False: return out('not_overturned'"),
    ('unknown_history_passes', "return out('not_overturned', 'needs_confirmation'", "return out('not_overturned', 'supported'"),
    ('sibling_order_passes', "'needs_confirmation', f'{src} is another court order", "'supported', f'{src} is another court order"),
    ('also_binding_passes', "'needs_confirmation', f'{src} binds", "'supported', f'{src} binds"),
    ('foreign_passes', "'unsupported', f'{src} is not the legal order", "'supported', f'{src} is not the legal order"),
    ('comparative_ignored', "    if ctx.get('comparative'):", '    if False:'),
    ('tier_ignored', "'needs_confirmation', 'only doctrine", "'supported', 'only doctrine"),
    ('decisive_ignored', "    if claim.get('decisive') is False: return None", '    if False: return None'),
    ('judge_upgraded', 'final = mapped if mapped and STATUS_RANK[mapped] > STATUS_RANK.get(st, -1) else st', "final = mapped or 'FOUND'"),
    ('unknown_tier_passes', "return out('source_tier', 'needs_confirmation', 'no anchor declares its tier')", "return out('source_tier', 'supported', 'x')"),
    ('skip_tiers_everything', "if r.get('tier') in SKIP_TIERS or kind_of(a) == 'doctrine': return None", "if r.get('tier'): return None"),
    ('flag_check_ignored', "if (why := flag_contradicts(r, start, last, ctx['today'])) is not None:", 'if (why := None) is not None:'),
    ('flag_inverted', "if now != (f in ('1', 'true')):", "if now == (f in ('1', 'true')):"),
    ('kind_filter_ignored', "    if k not in ('text', 'decision'): return None\n    if as_of is None", '    if as_of is None'),
    # rules added in VP (resolves, official text, coverage, bounded totals, versions, masking, mapping)
    ('malformed_resolves', "if not well_formed(i): return out('resolves', 'unsupported'", "if not well_formed(i): return out('resolves', 'supported'"),
    ('not_found_ignored', "if a['refusal'] and UNRESOLVED.match", "if False and UNRESOLVED.match"),
    ('verifier_not_found_ignored', "    if UNRESOLVED.match(vs):", '    if False:'),
    ('offline_resolves', "'needs_confirmation', f'{i}: not resolved offline", "'supported', f'{i}: not resolved offline"),
    ('res_fragment_passes', '(_RES|_INF)\\b|', '(_XXX)\\b|'),
    ('ag_opinion_passes', '(?:^|[:\\s])6\\d{4}CC|', ''),
    ('fabricated_as_distorted', "MAP = {'resolves': 'ABSENT',", "MAP = {'resolves': 'DISTORTED',"),
    ('foreign_as_distorted', "'jurisdiction_match': 'ABSENT',", "'jurisdiction_match': 'DISTORTED',"),
    ('official_as_distorted', "'official_text': 'SOURCE-UNAVAILABLE'}", "'official_text': 'DISTORTED'}"),
    ('flag_true_literal_ignored', "if now != (f in ('1', 'true')):", "if now != (f == '1'):"),   # the sentinel test itself is an equivalent mutant (9999 is always ahead)
    ('coverage_window_ignored', '    if cov and w < cov:', '    if False:'),
    ('negative_without_receipt_passes', "return out('coverage', 'needs_confirmation', 'negative claim without the receipt", "return out('coverage', 'supported', 'negative claim without the receipt"),
    ('bounded_complete_passes', "'unsupported', 'total presented as complete", "'supported', 'total presented as complete"),
    ('decision_after_date_passes', "if d > as_of: return out('in_force_at_date', 'unsupported'", "if d > as_of: return out('in_force_at_date', 'supported'"),
    ('consolidated_later_passes', "return out('version_pinned', 'unsupported'", "return out('version_pinned', 'supported'"),
    ('masked_end_not_open', "if masked and ctx.get('T') and (as_of", 'if False and (as_of'),
    ('missing_end_always_open', "if masked and ctx.get('T') and (as_of < ctx['T'] or inc and as_of == ctx['T']): continue", 'if True: continue'),
    ('legi_dead_passes', "return out('in_force_at_date', 'unsupported', f'LEGI state", "return out('in_force_at_date', 'supported', f'LEGI state"),
    ('needs_confirmation_not_flagged', "'flagged': bool(nc)", "'flagged': False"),
    ('verifier_absent_overridden', 'final = mapped if mapped and STATUS_RANK[mapped] > STATUS_RANK.get(st, -1) else st', 'final = mapped if mapped else st'),
    ('null_literal_kept', "NULLS = ('', 'undefined', 'null', 'none_literal')", "NULLS = ('',)"),
    ('later_set_aside_counted', "(later if ctx['as_of'] and dated.get(x) and dated[x] > ctx['as_of'] else by)", '(by)'),
    ('masked_on_T_exclusive_open', "(as_of < ctx['T'] or inc and as_of == ctx['T'])", "(as_of <= ctx['T'])"),
    ('card_over_record', "'rec': {**desc, **rec} if rec", "'rec': {**rec, **desc} if rec"),
]


def load_variant(src):
    m = types.ModuleType('law_checks_variant'); m.__file__ = str(TOOL)
    exec(compile(src, str(TOOL), 'exec'), m.__dict__)
    return m


def caught(M):
    """Names of the cases that fail on module M (empty = the module passes every case)."""
    bad = []
    for f in CASES:
        try: f(M)
        except Exception as e: bad.append(f'{f.__name__}: {type(e).__name__}')
    return bad


class Examples(unittest.TestCase):
    """The real examples of plugins/law.md and the run-directory mapping, on the shipped module."""
for _f in CASES:
    setattr(Examples, 'test_' + _f.__name__[5:], (lambda f: lambda self: f(L))(_f))


class Mutants(unittest.TestCase):
    def test_control_survives_and_every_mutant_is_caught(self):
        self.assertEqual(caught(load_variant(SRC.replace(CONTROL[1], CONTROL[2]))), [], 'control must pass every case')
        rows = []
        for name, old, new in MUTANTS:
            self.assertEqual(SRC.count(old), 1, f'{name}: anchor must occur exactly once')
            rows.append((name, caught(load_variant(SRC.replace(old, new)))))
        survivors = [n for n, b in rows if not b]
        self.assertEqual(survivors, [], f'surviving mutants: {survivors}')
        self.assertGreaterEqual(len(rows), 20)
        if os.environ.get('VP_MUTANTS_VERBOSE'):
            for n, b in rows: print(f'KILLED {n:34} by {b[0]}')
            print(f'{len(rows)}/{len(rows)} killed; control survived')


class CommandLine(unittest.TestCase):
    def test_cli_writes_law_checks_json_and_refuses_a_bad_date(self):
        with tempfile.TemporaryDirectory() as t:
            d = make_run(t, [{'id': 'A1', 'text': 'Intel GC holds.', 'source': {'key': 'S1'}, 'location': 'record'}], {'S1': {'celex': '62009TJ0286'}},
                         [('A1', 'FOUND', '')], {'S1': ('record.json', {'results': INTEL_GC['rec']})})
            r = subprocess.run([sys.executable, '-I', str(TOOL), str(d), '--as-of', '2020-01-01', '--order', 'EU', '--today', '2026-10-22'], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads((d / 'law_checks.json').read_text())
            self.assertEqual((out['claims'][0]['final_status'], out['to_apply']), ('DISTORTED', ['A1']))
            self.assertIn('62014CJ0413', out['claims'][0]['discrepancy'])
            self.assertEqual(json.loads((d / 'verdicts.json').read_text())['claims'][0]['status'], 'FOUND')     # verdicts.json untouched
            r = subprocess.run([sys.executable, '-I', str(TOOL), str(d), '--as-of', '1/1/2020'], capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)

    def test_verifier_saves_the_law_record_it_reads(self):
        import verifier as V
        class Fake:
            def read(self, ident): return {'call': 1, 'results': dict(INTEL_GC['rec'], id=ident, abstract='JUDGMENT TEXT')}
        with tempfile.TemporaryDirectory() as t:
            card = {'card_id': 'c', 'claims': [{'id': 'A1', 'text': 'x', 'source': {'key': 'S1'}}], 'sources': {'S1': {'celex': '62009TJ0286'}}}
            s = V.load_sources(card, gateway=Fake(), out_dir=t)
            self.assertEqual(s['S1']['origin'], 'abstract')
            self.assertEqual(json.loads((pathlib.Path(t) / 'S1' / 'record.json').read_text())['results']['set_aside_by'], ['62014CJ0413'])


if __name__ == '__main__':
    unittest.main()
