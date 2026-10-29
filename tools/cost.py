#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Cost announced before an expensive mode, and a user budget turned into a ceiling (SKILL.md section 0 "Cost and budget").
Standard library, no network, no model. Every figure comes from tools/config.json `costs` (measures written in CHANGELOG.md / README.md /
USAGE.md; orders of size, not quotes) and `call_cap`, `verifier.fulltext_cap`, `contradictor.families`.
Estimate: the base run (standard; law: long texts; code: with the whole reading before verdicts), plus the options asked:
  --fulltext (verifier reads the pinned full texts: fulltext_usd_per_text x verifier.fulltext_cap), --audit (x audit_factor),
  --contradictor F (one per family, `<via>[:<model>]`; a CLI on a subscription costs 0, an API call contradictor_api_call_usd; plus rereads).
  `expensive` = the options of costs.expensive present (the code plugin's whole reading counts as one): announce, and ask in an interactive session.
Budget: --budget USD, or a budget written in the user's words (--text "<question>": "budget 5 $", "5 USD max", "plafond de 5 dollars",
  "max. 5 €"...; euros are taken at par, said so). Under a budget every expensive mode is off; when the budget is below the base estimate,
  the gateway cap and the waves are scaled by budget / base: cap = max(costs.budget.min_cap, call_cap x ratio), waves = max(1,
  costs.budget.waves_full x ratio); the verifier keeps its own pool (verification is never cut). Write the plan in scope.md.
Usage: cost.py [--plugin P ...] [--fulltext] [--audit] [--contradictor F ...] [--budget USD | --text "<question>"] [--lang CODE] [--json]
Exit 0. Import: estimate(plugins, fulltext, audit, contradictors) -> dict; budget_in(text) -> (usd, currency) | None; plan(est, usd) -> dict."""
import argparse, json, pathlib, re, sys
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P))
import report_lang as RL   # noqa: E402

CONF = json.loads((P / 'config.json').read_text(encoding='utf-8'))
C = CONF.get('costs') or {}
CAP = int((CONF.get('call_cap') or {}).get('default', 60)); FT_CAP = int((CONF.get('verifier') or {}).get('fulltext_cap', 12))
EXPENSIVE = list(C.get('expensive') or [])
BUDGET = re.compile(r"(?:budget|plafond|ceiling|cap|max(?:imum)?\.?|presupuesto|l[ií]mite|tope|obergrenze|h[öo]chstens|bis zu)\s*(?:de|of|von|:|=)?\s*"
                    r"(?P<a>\d+(?:[.,]\d+)?)\s*(?P<c>\$|usd|dollars?|d[óo]lares|€|eur|euros?)"
                    r"|(?P<b>\d+(?:[.,]\d+)?)\s*(?P<d>\$|usd|dollars?|d[óo]lares|€|eur|euros?)\s*(?:max(?:imum)?|au plus|at most|maximum|como m[áa]ximo|h[öo]chstens|de budget|budget)"
                    r"|(?P<e>\$)\s*(?P<f>\d+(?:[.,]\d+)?)\s*(?:max(?:imum)?|budget|at most)", re.I)
TEXT = {
    'en': {'base': 'base run', 'law': 'law (long texts read whole)', 'code': 'code study with the whole reading', 'standard': 'standard run',
           'fulltext': 'full-text verification ({n} texts at most)', 'audit': 'audit mode (x{lo:g} to x{hi:g})',
           'contradictor': 'contradictor {f}', 'total': 'Estimated cost: {lo} to {hi} USD ({parts}).', 'total_one': 'Estimated cost: about {hi} USD ({parts}).',
           'confirm': 'Expensive option(s): {opts}. Confirm before launch (interactive session); orders of size from the measures, not a quote.',
           'nothing': 'No expensive option: no confirmation needed.',
           'budget': 'Budget {usd:g} USD{eur}: expensive options off ({off}); gateway cap {cap} calls, at most {waves} wave(s); the verifier keeps its own pool.',
           'budget_full': 'Budget {usd:g} USD{eur}: expensive options off ({off}); the base run fits (estimate {hi} USD): cap and waves unchanged.',
           'eur': ' (euros taken at par: no exchange rate in the skill)', 'below': 'The budget is below the smallest run ({min_usd} USD at {min_cap} calls): the report may be partial.',
           'none': 'none'},
    'fr': {'base': 'run de base', 'law': 'droit (textes longs lus en entier)', 'code': 'étude de code avec lecture complète', 'standard': 'run standard',
           'fulltext': 'vérification en texte intégral ({n} textes au plus)', 'audit': 'mode audit (x{lo:g} à x{hi:g})',
           'contradictor': 'contradicteur {f}', 'total': 'Coût estimé : {lo} à {hi} USD ({parts}).', 'total_one': 'Coût estimé : environ {hi} USD ({parts}).',
           'confirm': 'Option(s) coûteuse(s) : {opts}. Confirmer avant de lancer (session interactive) ; ordres de grandeur tirés des mesures, pas un devis.',
           'nothing': 'Aucune option coûteuse : pas de confirmation nécessaire.',
           'budget': 'Budget {usd:g} USD{eur} : options coûteuses désactivées ({off}) ; plafond de la passerelle {cap} appels, au plus {waves} vague(s) ; le vérificateur garde son propre budget.',
           'budget_full': 'Budget {usd:g} USD{eur} : options coûteuses désactivées ({off}) ; le run de base tient (estimation {hi} USD) : plafond et vagues inchangés.',
           'eur': ' (euros pris au pair : pas de taux de change dans le skill)', 'below': 'Le budget est sous le plus petit run ({min_usd} USD à {min_cap} appels) : le rapport risque d\'être partiel.',
           'none': 'aucune'},
}


def _t(lang, k, **kw):
    s = (TEXT.get(lang) or TEXT['en']).get(k) or TEXT['en'][k]
    return s.format(**kw) if kw else s


def _rng(x):
    if isinstance(x, dict): return float(x.get('low', 0)), float(x.get('high', x.get('low', 0)))
    return float(x), float(x)


def _via(family):
    v = str(family).split(':', 1)[0].strip().lower()
    return 'cli' if v in ('openai', 'claude', 'codex') else 'api'


def estimate(plugins=(), fulltext=False, audit=False, contradictors=()):
    names = {pathlib.Path(p).stem for p in plugins}
    if 'code' in names: base_key, (lo, hi) = 'code', _rng(C.get('code_whole_reading_usd', 7.0))
    elif 'law' in names: base_key, (lo, hi) = 'law', _rng(C.get('law_usd', {'low': 3.0, 'high': 10.0}))
    else: base_key, (lo, hi) = 'standard', _rng(C.get('standard_usd', {'low': 2.8, 'high': 3.0}))
    parts = [{'item': base_key, 'low': lo, 'high': hi}]
    if audit:
        f_lo, f_hi = _rng(C.get('audit_factor', {'low': 6, 'high': 7}))
        parts.append({'item': 'audit', 'low': round(lo * (f_lo - 1), 2), 'high': round(hi * (f_hi - 1), 2), 'factor': [f_lo, f_hi]})
    if fulltext:
        v = round(float(C.get('fulltext_usd_per_text', 0.75)) * FT_CAP, 2)
        parts.append({'item': 'fulltext', 'low': min(v, float(C.get('fulltext_extra_low_usd', v))), 'high': v, 'texts': FT_CAP})
    for f in contradictors:
        call = float(C.get('contradictor_cli_call_usd', 0.0) if _via(f) == 'cli' else C.get('contradictor_api_call_usd', 0.26))
        v = round(call + float(C.get('contradictor_rereads_usd', 0.6)), 2)
        parts.append({'item': 'contradictor', 'family': f, 'low': v, 'high': v})
    exp = [p['item'] if p['item'] != 'code' else 'code_whole_reading' for p in parts]
    exp = sorted({e for e in exp if e in EXPENSIVE})
    return {'base': base_key, 'parts': parts, 'low': round(sum(p['low'] for p in parts), 2), 'high': round(sum(p['high'] for p in parts), 2),
            'expensive': exp, 'confirm': bool(exp), 'currency': C.get('currency', 'USD')}


def budget_in(text):
    """(amount, 'USD'|'EUR') of a budget written in the user's words, or None."""
    m = BUDGET.search(str(text or ''))
    if not m: return None
    amount = m.group('a') or m.group('b') or m.group('f'); cur = (m.group('c') or m.group('d') or m.group('e') or '').lower()
    return float(amount.replace(',', '.')), ('EUR' if cur in ('€', 'eur', 'euro', 'euros') else 'USD')


def plan(est, usd):
    b = C.get('budget') or {}; waves_full = int(b.get('waves_full', 4)); min_cap = int(b.get('min_cap', 15))
    off = [e for e in EXPENSIVE]
    base = next(p for p in est['parts'] if p['item'] == est['base'])
    off_base = est['base'] == 'code'                      # the whole reading is an expensive option: under a budget, a standard study
    ref = _rng(C.get('standard_usd', {'low': 2.8, 'high': 3.0}))[1] if off_base else base['high']
    ratio = min(1.0, usd / ref) if ref > 0 else 1.0
    cap = max(min_cap, int(CAP * ratio)); waves = max(1, int(waves_full * ratio))
    return {'budget_usd': usd, 'expensive_off': off, 'base_estimate_usd': ref, 'ratio': round(ratio, 3), 'cap': cap if ratio < 1 else CAP,
            'waves_max': waves if ratio < 1 else None, 'reduced': ratio < 1, 'below_min': usd < round(ref * min_cap / CAP, 2),
            'min_usd': round(ref * min_cap / CAP, 2), 'min_cap': min_cap,
            'code_note': 'under a budget the code plugin runs without its whole reading before verdicts (SKILL.md "Cost and budget")' if off_base else ''}


def render(est, pl, lang, eur=False):
    names = {'standard': _t(lang, 'standard'), 'law': _t(lang, 'law'), 'code': _t(lang, 'code')}
    parts = []
    for p in est['parts']:
        lab = names.get(p['item']) or (_t(lang, 'fulltext', n=p.get('texts')) if p['item'] == 'fulltext' else
                                       _t(lang, 'audit', lo=p['factor'][0], hi=p['factor'][1]) if p['item'] == 'audit' else
                                       _t(lang, 'contradictor', f=p.get('family')))
        parts.append(f"{lab} {p['low']:g}" + (f"-{p['high']:g}" if p['high'] != p['low'] else ''))
    out = [_t(lang, 'total' if est['low'] != est['high'] else 'total_one', lo=f"{est['low']:g}", hi=f"{est['high']:g}", parts='; '.join(parts))]
    if pl is None: out.append(_t(lang, 'confirm', opts=', '.join(est['expensive'])) if est['confirm'] else _t(lang, 'nothing'))
    else:
        e = _t(lang, 'eur') if eur else ''
        off = ', '.join(pl['expensive_off']) or _t(lang, 'none')
        out.append(_t(lang, 'budget', usd=pl['budget_usd'], eur=e, off=off, cap=pl['cap'], waves=pl['waves_max']) if pl['reduced'] else
                   _t(lang, 'budget_full', usd=pl['budget_usd'], eur=e, off=off, hi=f"{pl['base_estimate_usd']:g}"))
        if pl['below_min']: out.append(_t(lang, 'below', min_usd=pl['min_usd'], min_cap=pl['min_cap']))
    return '\n'.join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Cost estimate before an expensive mode; a budget turned into a ceiling (no model).')
    ap.add_argument('--plugin', action='append', default=[]); ap.add_argument('--fulltext', action='store_true'); ap.add_argument('--audit', action='store_true')
    ap.add_argument('--contradictor', action='append', default=[]); ap.add_argument('--budget', type=float); ap.add_argument('--text')
    ap.add_argument('--lang'); ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    lang = a.lang if a.lang in RL.LANGS else (RL.detect(a.text) if a.text else 'en')
    est = estimate(a.plugin, a.fulltext, a.audit, a.contradictor)
    usd, eur = a.budget, False
    if usd is None and a.text and (b := budget_in(a.text)): usd, eur = b[0], b[1] == 'EUR'
    pl = plan(est, usd) if usd is not None else None
    if a.json: print(json.dumps({'estimate': est, 'budget': pl, 'euros_at_par': eur}, ensure_ascii=False, indent=1))
    else: print(render(est, pl, lang, eur))
    return 0


if __name__ == '__main__':
    sys.exit(main())
