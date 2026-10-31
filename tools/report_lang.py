#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Languages of the report (SKILL.md section 5, "Language"). Standard library, no network, no model.
The prose of REPORT.md, the progress lines and the final message are written in the user's language; the eight level-2 titles of the
output contract and the word of the finding headings have one version per language, in the table LANGS below (adding a language = adding
one entry, every key filled). JSON, identifiers, statuses (FOUND, DISTORTED...), file names and the working files (scope.md, searches/)
stay in English. Every tool that reads the titles (validate_card, export_report, export_data, passages, followups, living_diff,
evidence_bank, summary, progress) goes through sections() below, which returns the canonical (English) title of a known heading.
Usage: report_lang.py "<question>"        prints {"language": code, "titles": [...8], "finding": word} for the question's language
       report_lang.py --lang fr           the same for a given language        --list: the languages of the table
Import: LANGS; detect(text) -> code; canonical(title) -> English title or None; sections(md) -> [(canonical or raw title, body)];
raw_sections(md); title_language(titles) -> code; finding_re(lang=None); of_run(dir) -> code; msg(lang, key, **kw) -> str."""
import json, pathlib, re, sys, unicodedata

EN = ['Executive Summary', 'Introduction', 'Main Analysis', 'Synthesis & Insights', 'Limitations & Caveats', 'Recommendations', 'Bibliography',
      'Methodology Appendix']

# One entry per language. sections: the eight titles, in the order of EN. finding: word of `### <word> n — <title>`. coverage / active /
# skipped / unverified: words the mechanical checks 7 and 10 accept (regular expressions; the English words are accepted in every language,
# since tools such as check_keys.py print them). verdicts: words of a finding verdict -> the English scale word (living_diff, summary).
# stop: frequent words used by detect(). msg: the short sentences of the progress lines and of SUMMARY.md (str.format fields).
LANGS = {
    'en': {
        'name': 'English',
        'sections': EN, 'finding': 'Finding',
        'coverage': r'source coverage', 'active': r'active', 'skipped': r'skipped', 'unverified': r'unverified|not verified',
        'verdict_label': r'verdict',
        'verdicts': {'established': 'established', 'probable': 'probable', 'possible': 'possible', 'open': 'open', 'unlikely': 'unlikely',
                     'refuted': 'refuted'},
        'stop': ['the', 'and', 'of', 'what', 'is', 'are', 'how', 'which', 'to', 'for', 'does', 'do', 'with', 'on', 'from', 'before', 'known',
                 'about', 'was', 'were', 'has', 'have', 'this', 'that', 'by', 'or', 'an', 'it', 'its', 'can', 'there', 'between'],
        'msg': {
            'framing': 'VP: framing done, {angles} research angles, T = {T}.',
            'framing_none': 'VP: framing in progress.',
            'wave': 'VP: searches, {files} searcher file(s); since last update {calls} gateway call(s), {new} new document(s) (total {total_calls} calls, {total_ids} documents seen).',
            'writing': 'VP: writing the report ({findings} finding(s) so far).',
            'annex': 'VP: report written; extracting the claims to check.',
            'verifying': 'VP: verification of {claims} claim(s) under way.',
            'verified': 'VP: verification done, {claims} claim(s): {counts}.',
            'finished': 'VP: finished. {summary}',
            'answer': 'Answer', 'citations': 'Citations confirmed', 'coverage': 'Coverage and findings', 'cost': 'Cost', 'duration': 'Duration',
            'report': 'Report', 'files': 'Files',
            'citations_found': '{found} of {n} checked ({pct} %)',
            'citations_kept': '{found} of the {n} claims kept in verdicts.json (raw verifier output missing: claims removed unknown)',
            'citations_none': 'no verifier output',
            'angles_reached': '{k} of {n} research angles reached by a kept source',
            'studies': '{s} distinct studies ({b} bibliography entries, versions of one study counted once)',
            'sources': '{b} sources', 'source_one': '1 source',
            'few_sources': 'fewer than {k} distinct studies carry the report',
            'removed': '{k} removed from the report after verification', 'contra_checked': '{k} checked after the contradictor',
            'findings_verdicts': 'findings: {v}',
            'cost_given': '{usd} USD',
            'cost_partial': '{usd} USD known from the receipts of the verifier and nested tools (orchestrator and searchers not counted)',
            'cost_unknown': 'not known to the run files',
            'minutes': '{m} min', 'hours': '{h} h {m:02d} min',
            'pdf': 'PDF', 'followup': 'Follow-up {n}',
            'no_report': 'no REPORT.md in this directory',
            'colon': ': ',
            'contra_offer': "Codex is available: ask \"contradict this report\" for a review by a second model family (about {minutes} min; Codex adds no API cost, the rereads use your host model).",
        },
    },
    'fr': {
        'name': 'français',
        'sections': ['Résumé', 'Introduction', 'Analyse principale', 'Synthèse et enseignements', 'Limites et réserves', 'Recommandations',
                     'Bibliographie', 'Annexe méthodologique'],
        'finding': 'Constat',
        'coverage': r'couverture des sources', 'active': r'actives?|activ[ée]e?s?', 'skipped': r'ignor[ée]e?s?|écart[ée]e?s?|omise?s?',
        'unverified': r'non vérifiée?s?|pas vérifiée?s?|invérifiée?s?',
        'verdict_label': r'verdict',
        'verdicts': {'établi': 'established', 'établie': 'established', 'probable': 'probable', 'possible': 'possible', 'ouvert': 'open',
                     'ouverte': 'open', 'improbable': 'unlikely', 'réfuté': 'refuted', 'réfutée': 'refuted'},
        'stop': ['le', 'la', 'les', 'des', 'du', 'de', 'et', 'est', 'quel', 'quelle', 'quels', 'quelles', 'comment', 'pour', 'dans', 'sur',
                 'avec', 'une', 'un', 'que', 'qui', 'au', 'aux', 'ces', 'avant', 'depuis', 'sont', 'ou', 'pas', 'plus', 'entre', 'leur',
                 'leurs', 'cette', 'sait', 'connaît', 'on', 'qu', 'il', 'elle', 'ont', 'été', 'savoir', 'état', 'selon', 'chez'],
        'msg': {
            'framing': 'VP : cadrage fait, {angles} angles de recherche, T = {T}.',
            'framing_none': 'VP : cadrage en cours.',
            'wave': 'VP : recherches, {files} fichier(s) de chercheurs ; depuis le dernier point {calls} appel(s) à la passerelle, {new} nouveau(x) document(s) (total {total_calls} appels, {total_ids} documents vus).',
            'writing': 'VP : rédaction du rapport ({findings} constat(s) écrit(s)).',
            'annex': 'VP : rapport écrit ; extraction des affirmations à vérifier.',
            'verifying': 'VP : vérification de {claims} affirmation(s) en cours.',
            'verified': 'VP : vérification faite, {claims} affirmation(s) : {counts}.',
            'finished': 'VP : terminé. {summary}',
            'answer': 'Réponse', 'citations': 'Citations confirmées', 'coverage': 'Couverture et constats', 'cost': 'Coût', 'duration': 'Durée',
            'report': 'Rapport', 'files': 'Fichiers',
            'citations_found': '{found} sur {n} vérifiées ({pct} %)',
            'citations_kept': '{found} sur les {n} affirmations gardées dans verdicts.json (sortie brute du vérificateur absente : retraits inconnus)',
            'citations_none': 'pas de sortie du vérificateur',
            'angles_reached': '{k} angles de recherche sur {n} atteints par une source retenue',
            'studies': '{s} études distinctes ({b} entrées de bibliographie, versions d’une même étude comptées une fois)',
            'sources': '{b} sources', 'source_one': '1 source',
            'few_sources': 'moins de {k} études distinctes portent le rapport',
            'removed': '{k} retirées du rapport après vérification', 'contra_checked': '{k} vérifiées après le contradicteur',
            'findings_verdicts': 'constats : {v}',
            'cost_given': '{usd} USD',
            'cost_partial': '{usd} USD connus par les reçus du vérificateur et des outils imbriqués (orchestrateur et chercheurs non comptés)',
            'cost_unknown': 'inconnu des fichiers du run',
            'minutes': '{m} min', 'hours': '{h} h {m:02d} min',
            'pdf': 'PDF', 'followup': 'Complément {n}',
            'no_report': 'pas de REPORT.md dans ce dossier',
            'colon': ' : ',
            'contra_offer': "Codex est disponible : demandez « contredis ce rapport » pour une relecture par une seconde famille de modèles (environ {minutes} min ; Codex n'ajoute aucun coût d'API, les relectures utilisent votre modèle hôte).",
        },
    },
    'es': {
        'name': 'español',
        'sections': ['Resumen ejecutivo', 'Introducción', 'Análisis principal', 'Síntesis y conclusiones', 'Limitaciones y salvedades',
                     'Recomendaciones', 'Bibliografía', 'Apéndice metodológico'],
        'finding': 'Hallazgo',
        'coverage': r'cobertura de (?:las )?fuentes', 'active': r'activas?', 'skipped': r'omitidas?|descartadas?',
        'unverified': r'no verificad[ao]s?|sin verificar',
        'verdict_label': r'veredicto',
        'verdicts': {'establecido': 'established', 'establecida': 'established', 'probable': 'probable', 'posible': 'possible',
                     'abierto': 'open', 'abierta': 'open', 'improbable': 'unlikely', 'refutado': 'refuted', 'refutada': 'refuted'},
        'stop': ['el', 'los', 'las', 'del', 'y', 'es', 'qué', 'cuál', 'cuáles', 'cómo', 'para', 'con', 'una', 'por', 'sobre', 'antes', 'son',
                 'que', 'se', 'lo', 'su', 'sus', 'entre', 'según', 'sabe', 'hay', 'desde', 'fue'],
        'msg': {
            'framing': 'VP: planteamiento hecho, {angles} ángulos de búsqueda, T = {T}.',
            'framing_none': 'VP: planteamiento en curso.',
            'wave': 'VP: búsquedas, {files} archivo(s) de buscadores; desde el último aviso {calls} llamada(s) a la pasarela, {new} documento(s) nuevo(s) (total {total_calls} llamadas, {total_ids} documentos vistos).',
            'writing': 'VP: redacción del informe ({findings} hallazgo(s) por ahora).',
            'annex': 'VP: informe escrito; extracción de las afirmaciones que se verificarán.',
            'verifying': 'VP: verificación de {claims} afirmación(es) en curso.',
            'verified': 'VP: verificación hecha, {claims} afirmación(es): {counts}.',
            'finished': 'VP: terminado. {summary}',
            'answer': 'Respuesta', 'citations': 'Citas confirmadas', 'coverage': 'Cobertura y hallazgos', 'cost': 'Coste', 'duration': 'Duración',
            'report': 'Informe', 'files': 'Archivos',
            'citations_found': '{found} de {n} verificadas ({pct} %)',
            'citations_kept': '{found} de las {n} afirmaciones conservadas en verdicts.json (sin la salida bruta del verificador: retiradas desconocidas)',
            'citations_none': 'sin salida del verificador',
            'angles_reached': '{k} de {n} ángulos de búsqueda alcanzados por una fuente retenida',
            'studies': '{s} estudios distintos ({b} entradas de bibliografía, versiones de un mismo estudio contadas una vez)',
            'sources': '{b} fuentes', 'source_one': '1 fuente',
            'few_sources': 'menos de {k} estudios distintos sostienen el informe',
            'removed': '{k} retiradas del informe tras la verificación', 'contra_checked': '{k} verificadas tras el contradictor',
            'findings_verdicts': 'hallazgos: {v}',
            'cost_given': '{usd} USD',
            'cost_partial': '{usd} USD conocidos por los recibos del verificador y de las herramientas anidadas (orquestador y buscadores no contados)',
            'cost_unknown': 'desconocido para los archivos del run',
            'minutes': '{m} min', 'hours': '{h} h {m:02d} min',
            'pdf': 'PDF', 'followup': 'Complemento {n}',
            'no_report': 'no hay REPORT.md en este directorio',
            'colon': ': ',
            'contra_offer': "Codex está disponible: pida «contradice este informe» para una revisión por una segunda familia de modelos (unos {minutes} min; Codex no añade coste de API, las relecturas usan su modelo anfitrión).",
        },
    },
    'de': {
        'name': 'Deutsch',
        'sections': ['Zusammenfassung', 'Einleitung', 'Hauptanalyse', 'Synthese und Erkenntnisse', 'Grenzen und Vorbehalte', 'Empfehlungen',
                     'Literaturverzeichnis', 'Methodischer Anhang'],
        'finding': 'Befund',
        'coverage': r'quellenabdeckung|abdeckung der quellen', 'active': r'aktiv\w*', 'skipped': r'übersprungen\w*|ausgelassen\w*',
        'unverified': r'nicht (?:überprüft|verifiziert|geprüft)\w*|ungeprüft\w*',
        'verdict_label': r'urteil|bewertung',
        'verdicts': {'gesichert': 'established', 'belegt': 'established', 'wahrscheinlich': 'probable', 'möglich': 'possible', 'offen': 'open',
                     'unwahrscheinlich': 'unlikely', 'widerlegt': 'refuted'},
        'stop': ['der', 'die', 'das', 'und', 'ist', 'wie', 'welche', 'welcher', 'was', 'für', 'mit', 'ein', 'eine', 'von', 'vor', 'über', 'auf',
                 'sind', 'nicht', 'im', 'den', 'dem', 'des', 'zu', 'zur', 'zum', 'bei', 'nach', 'wird', 'werden', 'bekannt', 'zwischen'],
        'msg': {
            'framing': 'VP: Rahmen festgelegt, {angles} Suchwinkel, T = {T}.',
            'framing_none': 'VP: Rahmen in Arbeit.',
            'wave': 'VP: Suche, {files} Datei(en) der Sucher; seit der letzten Meldung {calls} Gateway-Aufruf(e), {new} neue(s) Dokument(e) (insgesamt {total_calls} Aufrufe, {total_ids} Dokumente gesehen).',
            'writing': 'VP: Bericht wird geschrieben ({findings} Befund(e) bisher).',
            'annex': 'VP: Bericht geschrieben; die zu prüfenden Aussagen werden extrahiert.',
            'verifying': 'VP: Prüfung von {claims} Aussage(n) läuft.',
            'verified': 'VP: Prüfung abgeschlossen, {claims} Aussage(n): {counts}.',
            'finished': 'VP: fertig. {summary}',
            'answer': 'Antwort', 'citations': 'Bestätigte Zitate', 'coverage': 'Abdeckung und Befunde', 'cost': 'Kosten', 'duration': 'Dauer',
            'report': 'Bericht', 'files': 'Dateien',
            'citations_found': '{found} von {n} geprüften ({pct} %)',
            'citations_kept': '{found} der {n} in verdicts.json behaltenen Aussagen (Rohausgabe des Prüfers fehlt: Entfernungen unbekannt)',
            'citations_none': 'keine Ausgabe des Prüfers',
            'angles_reached': '{k} von {n} Suchwinkeln durch eine behaltene Quelle erreicht',
            'studies': '{s} verschiedene Studien ({b} Einträge im Literaturverzeichnis, Versionen einer Studie einmal gezählt)',
            'sources': '{b} Quellen', 'source_one': '1 Quelle',
            'few_sources': 'weniger als {k} verschiedene Studien tragen den Bericht',
            'removed': '{k} nach der Prüfung aus dem Bericht entfernt', 'contra_checked': '{k} nach dem Widerspruchsprüfer geprüft',
            'findings_verdicts': 'Befunde: {v}',
            'cost_given': '{usd} USD',
            'cost_partial': '{usd} USD laut den Belegen des Prüfers und der eingebetteten Werkzeuge (Orchestrator und Sucher nicht gezählt)',
            'cost_unknown': 'den Dateien des Laufs nicht bekannt',
            'minutes': '{m} min', 'hours': '{h} h {m:02d} min',
            'pdf': 'PDF', 'followup': 'Ergänzung {n}',
            'no_report': 'kein REPORT.md in diesem Verzeichnis',
            'colon': ': ',
            'contra_offer': "Codex ist verfügbar: Bitten Sie „widersprich diesem Bericht“ um eine Prüfung durch eine zweite Modellfamilie (etwa {minutes} Min.; Codex verursacht keine API-Kosten, die Nachprüfungen nutzen Ihr Host-Modell).",
        },
    },
}
DEFAULT = 'en'
HINTS = {'fr': 'éèêàçùœâîôû', 'es': 'ñ¿¡áíóú', 'de': 'äöüß'}   # characters that weigh for a language in detect() (one point each, words count two)


def _norm(t):
    return ' '.join(unicodedata.normalize('NFC', str(t or '')).split()).casefold()


CANON = {_norm(t): EN[i] for code, L in LANGS.items() for i, t in enumerate(L['sections'])}


def detect(text):
    """Language code of a question or report text: frequent words (two points) and accented letters (one point); ties and empty text -> en."""
    t = unicodedata.normalize('NFC', str(text or '')).casefold()
    words = re.findall(r"[^\W\d_]+", t)
    score = {}
    for code, L in LANGS.items():
        stop = set(L['stop'])
        score[code] = 2 * sum(1 for w in words if w in stop) + sum(t.count(c) for c in HINTS.get(code, ''))
    best = max(score.values()) if score else 0
    if best == 0: return DEFAULT
    winners = [c for c, s in score.items() if s == best]
    return DEFAULT if DEFAULT in winners else winners[0]


def canonical(title):
    """English title of a known level-2 heading of any language of the table, else None."""
    return CANON.get(_norm(title))


def raw_sections(md):
    """[(title as written, body)] of the level-2 headings, in file order."""
    parts = re.split(r'^## +(.+?)\s*$', md or '', flags=re.M)
    return [(parts[i].strip(), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]


def sections(md):
    """[(canonical English title, or the raw title when unknown, body)] in file order."""
    return [(canonical(t) or t, b) for t, b in raw_sections(md)]


def section(md, title):
    """Body of the section whose canonical title is `title` (English), '' when absent."""
    return next((b for t, b in sections(md) if t == title), '')


def title_language(titles):
    """Language whose table titles match the most of `titles` (ties -> en, then table order); en when none matches."""
    best, code = 0, DEFAULT
    for c, L in LANGS.items():
        n = sum(1 for t in titles if _norm(t) in {_norm(x) for x in L['sections']})
        if n > best: best, code = n, c
    return code


def report_language(md):
    return title_language([t for t, _ in raw_sections(md)])


def finding_words():
    return [L['finding'] for L in LANGS.values()]


def finding_re(lang=None):
    """`### <word> n — <title>` heading, for one language or any of the table (group 1: n, group 2: title; em dash or hyphen accepted on read)."""
    words = [LANGS[lang]['finding']] if lang else finding_words()
    return re.compile(r'^### +(?:' + '|'.join(re.escape(w) for w in words) + r') +(\d+)\s*[—-]+\s*(.+?)\s*$', re.M)


def any_words(key):
    """One regular expression accepting the words `key` (coverage, active, skipped, unverified) of every language of the table."""
    return re.compile('|'.join(f'(?:{L[key]})' for L in LANGS.values()), re.I)


def verdict_word(text):
    """English scale word of the first verdict word (by position) found in `text`, any language of the table; None when none."""
    t = _norm(text); best = None
    for L in LANGS.values():
        for w, en in L['verdicts'].items():
            m = re.search(r'(?<!\w)' + re.escape(w) + r'(?!\w)', t)
            if m and (best is None or m.start() < best[0]): best = (m.start(), en)
    return best[1] if best else None


def scope_language(text):
    m = re.search(r'\bReport language(?:\*\*)?\s*[:=]\s*`?([a-z]{2})\b', text or '', re.I)   # not the criterion "Language:" of the documents
    return m.group(1).lower() if m and m.group(1).lower() in LANGS else None


def of_run(folder):
    """Language of a run: `Report language: xx` of scope.md, else the titles of REPORT.md, else the question of card.json, else en."""
    d = pathlib.Path(folder)
    def read(p):
        try: return p.read_text(encoding='utf-8', errors='replace')
        except OSError: return ''
    if (c := scope_language(read(d / 'scope.md'))): return c
    rep = read(d / 'REPORT.md')
    if rep and any(canonical(t) for t, _ in raw_sections(rep)): return report_language(rep)
    try: q = json.loads(read(d / 'card.json') or '{}').get('question') or ''
    except ValueError: q = ''
    try: q = q or json.loads(read(d / 'state' / 'run-start.json') or '{}').get('question') or ''
    except ValueError: pass
    return detect(q) if q else DEFAULT


def msg(lang, key, **kw):
    m = LANGS.get(lang, LANGS[DEFAULT])['msg'].get(key) or LANGS[DEFAULT]['msg'][key]
    return m.format(**kw) if kw and isinstance(m, str) else m


def describe(lang):
    L = LANGS[lang]
    return {'language': lang, 'name': L['name'], 'titles': L['sections'], 'finding': L['finding'],
            'finding_heading': f"### {L['finding']} n — <title>"}


if __name__ == '__main__':
    a = sys.argv[1:]
    if not a or a[0] in ('-h', '--help'): print(__doc__); sys.exit(0 if a else 2)
    if a[0] == '--list': print(json.dumps({c: L['name'] for c, L in LANGS.items()}, ensure_ascii=False)); sys.exit(0)
    if a[0] == '--lang':
        if len(a) < 2 or a[1] not in LANGS: print(f'unknown language; table: {", ".join(LANGS)}', file=sys.stderr); sys.exit(2)
        print(json.dumps(describe(a[1]), ensure_ascii=False, indent=1)); sys.exit(0)
    print(json.dumps(describe(detect(' '.join(a))), ensure_ascii=False, indent=1))
