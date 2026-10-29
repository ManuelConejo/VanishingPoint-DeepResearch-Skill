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
  "max. 5 €"...; euros are taken at par, said so). Under a budget every expensive mode is off and the budget covers the whole run,
  verification included: costs.budget.verifier_share of it is reserved for the verifier (verifier_usd), the rest (search_usd) pays the
  orchestrator and the searchers, a fixed part plus a part per gateway call (trace_model(), derived from costs.trace_calibration):
  cap = (search_usd - trace_usd_fixed) / trace_usd_per_call, bounded by costs.budget.min_cap and call_cap.default; waves = max(1, costs.budget.waves_full x cap / call_cap.default). With --state DIR the plan
  is written to DIR/budget.json: tools/gateway.py takes its `cap` when no --cap is given, tools/verifier.py takes `verifier_usd` as its
  spending limit (no model call beyond it). Write the plan in scope.md.
Usage: cost.py [--plugin P ...] [--fulltext] [--audit] [--contradictor F ...] [--budget USD | --text "<question>"] [--state DIR] [--lang CODE] [--json]
Exit 0. Import: trace_model() -> (usd per call, fixed usd); estimate(plugins, fulltext, audit, contradictors) -> dict; budget_in(text) -> (usd, currency) | None; plan(est, usd) -> dict;
  write_plan(state_dir, plan, eur=False) -> path."""
import argparse, datetime as dt, json, math, pathlib, re, sys
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
           'budget': 'Budget {usd:g} USD{eur}, verification included: expensive options off ({off}); {ver:g} USD reserved for the verifier, {search:g} USD for the searches: gateway cap {cap} calls, at most {waves} wave(s).',
           'budget_full': 'Budget {usd:g} USD{eur}, verification included: expensive options off ({off}); {ver:g} USD reserved for the verifier, {search:g} USD for the searches: cap and waves unchanged.',
           'eur': ' (euros taken at par: no exchange rate in the skill)', 'below': 'The budget is below the smallest run ({min_usd} USD at {min_cap} calls): the report may be partial.',
           'thin': 'The verifier reserve ({ver:g} USD) is below the highest verification measured ({hi:g} USD): claims beyond it stay UNVERIFIED.',
           'none': 'none'},
    'fr': {'base': 'run de base', 'law': 'droit (textes longs lus en entier)', 'code': 'étude de code avec lecture complète', 'standard': 'run standard',
           'fulltext': 'vérification en texte intégral ({n} textes au plus)', 'audit': 'mode audit (x{lo:g} à x{hi:g})',
           'contradictor': 'contradicteur {f}', 'total': 'Coût estimé : {lo} à {hi} USD ({parts}).', 'total_one': 'Coût estimé : environ {hi} USD ({parts}).',
           'confirm': 'Option(s) coûteuse(s) : {opts}. Confirmer avant de lancer (session interactive) ; ordres de grandeur tirés des mesures, pas un devis.',
           'nothing': 'Aucune option coûteuse : pas de confirmation nécessaire.',
           'budget': 'Budget {usd:g} USD{eur}, vérification comprise : options coûteuses désactivées ({off}) ; {ver:g} USD réservés au vérificateur, {search:g} USD aux recherches : plafond de la passerelle {cap} appels, au plus {waves} vague(s).',
           'budget_full': 'Budget {usd:g} USD{eur}, vérification comprise : options coûteuses désactivées ({off}) ; {ver:g} USD réservés au vérificateur, {search:g} USD aux recherches : plafond et vagues inchangés.',
           'eur': ' (euros pris au pair : pas de taux de change dans le skill)', 'below': 'Le budget est sous le plus petit run ({min_usd} USD à {min_cap} appels) : le rapport risque d\'être partiel.',
           'thin': 'La réserve du vérificateur ({ver:g} USD) est sous la plus haute vérification mesurée ({hi:g} USD) : les affirmations au-delà restent UNVERIFIED.',
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


def trace_model(runs=None):
    """(usd per search call, fixed usd) of a run's trace, from costs.trace_calibration.runs: least-squares slope of usd on calls, and the
    highest intercept that keeps every measured run under the line, rounded up to the cent (an upper envelope: no measured run above it)."""
    runs = runs if runs is not None else (C.get('trace_calibration') or {}).get('runs') or []
    pts = [(float(r['calls']), float(r['usd'])) for r in runs]
    if len({n for n, _ in pts}) < 2: raise ValueError('costs.trace_calibration.runs needs runs at two different numbers of calls at least')
    mn = sum(n for n, _ in pts) / len(pts); mu = sum(u for _, u in pts) / len(pts)
    per = sum((n - mn) * (u - mu) for n, u in pts) / sum((n - mn) ** 2 for n, _ in pts)
    per = max(per, 0.0)
    fixed = max(u - per * n for n, u in pts)
    return round(per, 4), math.ceil(round(max(fixed, 0.0) * 100, 6)) / 100


def plan(est, usd):
    """The budget covers the whole run, verification included: a share reserved for the verifier, the rest turned into a gateway cap."""
    b = C.get('budget') or {}; waves_full = int(b['waves_full']); min_cap = int(b['min_cap']); share = float(b['verifier_share'])
    per_call, fixed = trace_model(); ver_hi = _rng(C['verifier_usd'])[1]
    off = [e for e in EXPENSIVE]
    base = next(p for p in est['parts'] if p['item'] == est['base'])
    off_base = est['base'] == 'code'                      # the whole reading is an expensive option: under a budget, a standard study
    ref = _rng(C['standard_usd'])[1] if off_base else base['high']
    ver = round(usd * share, 2); search = round(usd - ver, 2)
    fit = int(max(search - fixed, 0) / per_call) if per_call > 0 else CAP
    cap = max(min_cap, min(CAP, fit)); reduced = fit < CAP
    min_usd = round((fixed + min_cap * per_call) / (1 - share), 2) if share < 1 else None
    return {'budget_usd': usd, 'expensive_off': off, 'base_estimate_usd': ref, 'verifier_usd': ver, 'search_usd': search,
            'trace_usd_per_call': per_call, 'trace_usd_fixed': fixed, 'ratio': round(cap / CAP, 3), 'cap': cap,
            'waves_max': max(1, int(waves_full * cap / CAP)) if reduced else None, 'reduced': reduced,
            'below_min': fit < min_cap, 'min_usd': min_usd, 'min_cap': min_cap, 'verifier_thin': ver < ver_hi, 'verifier_high_usd': ver_hi,
            'code_note': 'under a budget the code plugin runs without its whole reading before verdicts (SKILL.md "Cost and budget")' if off_base else ''}


def write_plan(state_dir, pl, eur=False):
    """state/budget.json: read by tools/gateway.py (cap, when no --cap) and tools/verifier.py (verifier_usd, its spending limit)."""
    st = pathlib.Path(state_dir); st.mkdir(parents=True, exist_ok=True)
    keep = ('budget_usd', 'verifier_usd', 'search_usd', 'cap', 'waves_max', 'reduced', 'trace_usd_per_call', 'trace_usd_fixed', 'expensive_off')
    doc = {**{k: pl[k] for k in keep}, 'euros_at_par': bool(eur), 'written_utc': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}
    (st / 'budget.json').write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    return st / 'budget.json'


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
        out.append(_t(lang, 'budget', usd=pl['budget_usd'], eur=e, off=off, ver=pl['verifier_usd'], search=pl['search_usd'], cap=pl['cap'], waves=pl['waves_max'])
                   if pl['reduced'] else _t(lang, 'budget_full', usd=pl['budget_usd'], eur=e, off=off, ver=pl['verifier_usd'], search=pl['search_usd']))
        if pl['below_min']: out.append(_t(lang, 'below', min_usd=pl['min_usd'], min_cap=pl['min_cap']))
        if pl['verifier_thin']: out.append(_t(lang, 'thin', ver=pl['verifier_usd'], hi=pl['verifier_high_usd']))
    return '\n'.join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Cost estimate before an expensive mode; a budget turned into a ceiling (no model).')
    ap.add_argument('--plugin', action='append', default=[]); ap.add_argument('--fulltext', action='store_true'); ap.add_argument('--audit', action='store_true')
    ap.add_argument('--contradictor', action='append', default=[]); ap.add_argument('--budget', type=float); ap.add_argument('--text')
    ap.add_argument('--state', help='with a budget: write the plan to STATE/budget.json (read by the gateway and the verifier)')
    ap.add_argument('--lang'); ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    lang = a.lang if a.lang in RL.LANGS else (RL.detect(a.text) if a.text else 'en')
    est = estimate(a.plugin, a.fulltext, a.audit, a.contradictor)
    usd, eur = a.budget, False
    if usd is None and a.text and (b := budget_in(a.text)): usd, eur = b[0], b[1] == 'EUR'
    pl = plan(est, usd) if usd is not None else None
    if pl is not None and a.state: write_plan(a.state, pl, eur)
    if a.json: print(json.dumps({'estimate': est, 'budget': pl, 'euros_at_par': eur}, ensure_ascii=False, indent=1))
    else: print(render(est, pl, lang, eur))
    return 0


if __name__ == '__main__':
    sys.exit(main())
