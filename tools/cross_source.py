#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check 14 of validate_card.py: cross-source statements carrying a single citation (SKILL.md sections 5 and 8). Standard library, no
network, no model.
A sentence that compares, ranks, counts, excludes or reports a search outcome across sources ("the largest series [5]", "the only trial
above 60 patients [3]", "excluded [12]", "sensitivity ranges from 52 % to 95 % [1]", "no later ruling was found [13]") is the writer's
synthesis: the cited source cannot say it, so a verifier or a reader checking that [n] finds it unsupported (lab analysis of 2026-10-29:
about half of the precise-claim errors of the judged duels were such sentences, with correct figures but a single-source citation on a
cross-source statement). The check finds them mechanically; the writer then rewrites each one: the fact of [n] in its own sentence with
its [n], and the comparison, count, exclusion or search outcome as an explicit synthesis without [n] ("Of the series read, ..."), or the
sentence cites every source it compares.
Unit = the clause that carries one citation group, as a judge pairs it: within a sentence, the text since the previous citation group up
to this group (the text after the last group joins the last clause); adjacent groups ("[2][9]", "[2], [9]") form one group. A clause is
flagged when it holds a marker of the report's language (MARKERS, one entry per language of tools/report_lang.py; English is also read in
every language) and its group names exactly one source. Sections skipped: config.json `cross_source.skip_sections` (canonical titles).
Usage: cross_source.py REPORT.md [--json]       Import: flagged(md) -> [dict]; problems(md) -> [str] (lines of check 14, empty = OK)."""
import json, pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import report_lang as RL   # noqa: E402

CFG = (json.loads((pathlib.Path(__file__).resolve().parent / 'config.json').read_text(encoding='utf-8')).get('cross_source') or {})

_N = r'(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty)'
_NFR = r'(?:deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|quinze|vingt)'
_NES = r'(?:dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|quince|veinte)'
_NDE = r'(?:zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn|elf|zwölf|fünfzehn|zwanzig)'
_SRC = r'(?:stud(?:y|ies)|trials?|series|sources?|papers?|articles?|records?|cohorts?|judg(?:e)?ments?|decisions?|rulings?|reviews?)'
_SFR = r'(?:études?|essais?|séries?|sources?|travaux|rapports?|notices?|cohortes?|décisions?|arrêts?|jugements?|revues?)'
_SES = r'(?:estudios?|ensayos?|series?|fuentes?|trabajos?|informes?|registros?|cohortes?|decisiones?|sentencias?|revisiones?)'
_SDE = r'(?:Studien|Studie|Serien|Serie|Quellen|Quelle|Arbeiten|Berichte|Kohorten|Urteile|Urteil|Entscheidungen|Entscheidung|Übersichten)'
# nouns counted by `count of sources` (a narrower list: a single review counting its papers, or a venue name such as 'Long Papers', is not a count of the sources read)
_CEN = r'(?:stud(?:y|ies)|trials|series|sources|cohorts|judg(?:e)?ments|decisions|rulings)'
_CFR = r'(?:études|essais|séries|sources|cohortes|décisions|arrêts|jugements)'
_CES = r'(?:estudios|ensayos|series|fuentes|cohortes|decisiones|sentencias)'
_CDE = r'(?:Studien|Serien|Quellen|Kohorten|Urteile|Entscheidungen)'

# Marker families, derived from the 54 cross-source errors (SYN) and 2 own computations (CALC) of the judged duels and the 15 cross-source
# verifier verdicts classified in our bench analysis of 2026-10-29: superlative or rank, exclusivity, count of sources, exclusion, range or
# variation across sources, quantifier over sources, search outcome or reading status, own computation, overlap of sources.
MARKERS = {
    'en': [
        ('superlative', r'\b(?:largest|smallest|biggest|highest|lowest|earliest)\b'),
        ('exclusivity', r'\b(?:the only|only (?:one|two|three|four|five|a few)\b|none (?:of|is|was|were|reports?)|neither (?:of|paper|study|source)|no (?:other|larger|later|earlier|further|similar)\b|no ' + _SRC + r'\b)'),
        ('count of sources', r'\b' + _N + r'(?: (?!of\b)\w+)? ' + _CEN + r'\b'),
        ('exclusion', r'\b(?:excluded|not included|not eligible|ineligible)\b'),
        ('range across sources', r'\b(?:ranges? (?:from|between)|ranging from|runs? from|var(?:y|ies|ied) (?:across|between|from|widely))\b'),
        ('quantifier over sources', r'\b(?:across|among|between) (?:the )?(?:\w+ )?' + _SRC + r'\b|\b(?:most|all|several|many|few|both|other|some) (?:of the )?(?:\w+ )?' + _SRC + r'\b|\bother work\b'),
        ('search outcome', r'\b(?:not (?:read|retrieved|found|seen|served|accessible)|could not be (?:read|retrieved|found|accessed)|we found|found (?:none|nothing)|returned nothing|in this search|seen in this search|by title only)\b'),
        ('own computation', r'\b(?:my|our|own) (?:computation|calculation|count)\b|\bcomputed (?:from|by)\b'),
        ('overlap of sources', r'\b(?:overlap(?:s|ping)?|same (?:team|centre|center|group|cohort|authors))\b'),
    ],
    'fr': [
        ('superlative', r'\b(?:le|la|les) plus (?:grand|petit|élev|faibl|bas|haut|fort|large|longu?|court|ancien|récent)\w*|\b(?:le|la) (?:maximum|minimum)\b'),
        ('exclusivity', r"\b(?:le seul|la seule|les seul(?:e)?s|seul(?:e)?s (?:deux|trois|quatre|cinq)|aucun(?:e)? (?:autre|des|plus)\b|aucun(?:e)? " + _SFR + r"|ni l'une?|nulle part)"),
        ('count of sources', r'\b' + _NFR + r'(?: \w+)? ' + _CFR + r'(?!\w)'),
        ('exclusion', r'\b(?:exclu(?:e)?s?|écarté(?:e)?s?|non inclu(?:se?|s)|non éligibles?|inéligibles?)(?!\w)'),
        ('range across sources', r"\b(?:va(?:rie|rient|ont)? de|vont de|allant de|s'étend(?:ent)? de|s'échelonn\w*|fourchette)(?!\w)"),
        ('quantifier over sources', r"\b(?:parmi|entre|à travers) (?:les|ces) (?:\w+ )?" + _SFR + r"|\b(?:la plupart|la majorité|plusieurs|toutes|tous|quelques|d'autres|les deux)(?: des| les| de)? (?:\w+ )?" + _SFR + r"(?!\w)"),
        ('search outcome', r"\b(?:non lu(?:e)?s?|pas (?:été )?(?:lu|trouvé|récupéré|vu|servi)\w*|n'a pas pu être \w+|n'ont pas pu être \w+|introuvables?|dans cette recherche|nous avons trouvé|(?:a|ont) été trouvé\w*|trouvé(?:e)?s? aucun\w*|sur titre seul\w*|au seul titre)(?!\w)"),
        ('own computation', r'\b(?:mon|notre|propre) (?:calcul|décompte)|\bcalculé(?:e)?s? (?:à partir|par nous|d’après|d\'après)'),
        ('overlap of sources', r'\b(?:chevauch\w*|recoup\w*|même (?:équipe|centre|groupe|cohorte|auteurs?))'),
    ],
    'es': [
        ('superlative', r'\b(?:el|la|los|las) (?:más (?:grande|pequeñ|alt|baj|amplio|larg|cort|antigu|recient)\w*|mayor(?:es)?|menor(?:es)?)\b'),
        ('exclusivity', r'\b(?:el único|la única|los únicos|las únicas|s[oó]lo (?:dos|tres|cuatro|cinco)|ningun(?:o|a)? (?:otr[oa]|de|más)\b|ningun(?:o|a)? ' + _SES + r'|ninguno)'),
        ('count of sources', r'\b' + _NES + r'(?: \w+)? ' + _CES + r'(?!\w)'),
        ('exclusion', r'\b(?:excluid[oa]s?|descartad[oa]s?|no incluid[oa]s?|no elegibles?)(?!\w)'),
        ('range across sources', r'\b(?:van de|va de|va desde|oscila(?:n)? entre|varía(?:n)? (?:de|entre)|rango de)(?!\w)'),
        ('quantifier over sources', r'\b(?:entre|en) (?:los|las|estos|estas) (?:\w+ )?' + _SES + r'|\b(?:la mayoría de|todos|todas|varios|varias|algunos|algunas|muchos|muchas|otros|otras|ambos|ambas)(?: los| las| de los| de las)? (?:\w+ )?' + _SES + r'(?!\w)'),
        ('search outcome', r'\b(?:no (?:fue |fueron |se )?(?:leíd|encontr|recuperad|vist)\w*|no (?:se )?pud(?:o|ieron) (?:leer|encontrar|recuperar)|en esta búsqueda|(?:se )?encontr(?:ó|aron|amos)|sólo por (?:el )?título|solo por (?:el )?título)(?!\w)'),
        ('own computation', r'\b(?:mi|nuestro|propio) (?:cálculo|recuento)|\bcalculad[oa]s? a partir'),
        ('overlap of sources', r'\b(?:solap\w*|superpon\w*|mism[oa] (?:equipo|centro|grupo|cohorte|autores?))'),
    ],
    'de': [
        ('superlative', r'\b(?:größt|kleinst|höchst|niedrigst|geringst|umfangreichst|längst|kürzest|frühest)\w*'),
        ('exclusivity', r'\b(?:einzig\w*|nur (?:zwei|drei|vier|fünf|eine?)\b|kein\w* (?:andere\w*|der|weitere\w*|größere\w*)\b|kein\w* ' + _SDE + r')'),
        ('count of sources', r'\b' + _NDE + r'(?: \w+)? ' + _CDE + r'(?!\w)'),
        ('exclusion', r'\b(?:ausgeschlossen|nicht eingeschlossen|nicht einschlussfähig)(?!\w)'),
        ('range across sources', r'\b(?:reicht\w* von|lieg(?:t|en) zwischen|schwank\w*|Spanne|Bandbreite)(?!\w)'),
        ('quantifier over sources', r'\b(?:über|unter|zwischen) (?:den|allen|diesen) (?:\w+ )?' + _SDE + r'|\b(?:die meisten|alle|mehrere|einige|viele|wenige|beide|andere)(?: der| den)? (?:\w+ )?' + _SDE + r'(?!\w)'),
        ('search outcome', r'\b(?:nicht (?:gelesen|gefunden|abgerufen|zugänglich|verfügbar)|konnte\w* nicht (?:gelesen|gefunden|abgerufen) werden|in dieser Suche|wurde\w* gefunden|fanden wir|nur (?:nach|anhand des?) Titel\w*)(?!\w)'),
        ('own computation', r'\b(?:eigene\w* (?:Berechnung|Zählung)|von uns berechnet|berechnet aus)'),
        ('overlap of sources', r'\b(?:überschneid\w*|überlapp\w*|(?:dasselbe|derselben|demselben|selben) (?:Team|Gruppe|Zentrum|Kohorte|Autoren))'),
    ],
}
COMPILED = {lang: [(fam, re.compile(rx, re.I)) for fam, rx in fams] for lang, fams in MARKERS.items()}

GROUP = re.compile(r'\[\d{1,3}(?:\s*[,;–-]\s*\d{1,3})*\](?:\s*,?\s*\[\d{1,3}(?:\s*[,;–-]\s*\d{1,3})*\])*')
ABBR = re.compile(r'\b(?:et al|e\.g|i\.e|vs|Fig|No|Art|art|cf|approx|Vol|pp|Eq|Tab|Sec|Ref|Dr|St|Inc|Ltd|v|n°|p|S|Nr|bzw|z\.B|ca|Abs)\.', re.I)
DESIGNATION = re.compile(r'`?\s*/\s*`?A\d+')   # "`[n]` / `A<k>`": a claim designated in the methodology appendix (SKILL.md section 5), not a citation
SPLIT = re.compile(r'(?<=[.!?…])\s+(?=[A-ZÀ-ÖØ-Þ"“«(\[¿¡*_])')


def numbers(group):
    """Distinct source numbers of a citation group: [5] -> {5}; [5, 10] -> {5, 10}; [12-14] -> {12, 13, 14}; [2][9] -> {2, 9}."""
    out = set()
    for b in re.findall(r'\[([^\]]*)\]', group):
        for part in re.split(r'\s*[,;]\s*', b):
            m = re.fullmatch(r'\s*(\d+)\s*[–-]\s*(\d+)\s*', part)
            if m: out |= set(range(int(m.group(1)), int(m.group(2)) + 1))
            elif part.strip().isdigit(): out.add(int(part))
    return out


def sentences(text):
    """Sentences of a section body: paragraphs and list items, then sentence ends (abbreviations and decimals protected)."""
    out = []
    for para in re.split(r'\n\s*\n|\n(?=\s*(?:[-*+]|\d+[.)])\s)', text):
        para = ' '.join(l.strip() for l in para.splitlines() if l.strip() and not l.lstrip().startswith('#'))
        if not para: continue
        prot = ABBR.sub(lambda m: m.group(0).replace('.', '\x00'), para)
        prot = re.sub(r'(\d)\.(\d)', '\\1\x00\\2', prot)
        out += [s.replace('\x00', '.').strip() for s in SPLIT.split(prot) if s.strip()]
    return out


def clauses(s):
    """[(clause text, citation group)] of a sentence, in the judges' pairing: each group gets the text since the previous group; the text
    after the last group joins the last clause."""
    ms = [m for m in GROUP.finditer(s) if not DESIGNATION.match(s, m.end())]; out = []; start = 0
    for k, m in enumerate(ms):
        end = len(s) if k == len(ms) - 1 else m.end()
        out.append((s[start:end], m.group(0))); start = m.end()
    return out


def markers(text, lang):
    """[(family, matched words)] of the markers of `lang` (plus English) found in text (citation groups removed)."""
    t = GROUP.sub(' ', text); found = []
    for lg in dict.fromkeys([lang if lang in COMPILED else 'en', 'en']):
        for fam, rx in COMPILED[lg]:
            m = rx.search(t)
            if m and (fam, m.group(0)) not in found: found.append((fam, m.group(0)))
    return found


def flagged(md, lang=None):
    """Sentences of REPORT.md with a clause that holds a cross-source marker and cites exactly one source:
    [{'section', 'sentence', 'citation', 'markers'}], in file order."""
    lang = lang or RL.title_language([s for s, _ in RL.raw_sections(md)])
    skip = set(CFG.get('skip_sections') or ['Bibliography']); out = []
    for title, body in RL.sections(md):
        if title in skip: continue
        for s in sentences(body):
            for clause, group in clauses(s):
                ns = numbers(group)
                if len(ns) != 1: continue
                mk = markers(clause, lang)
                if mk: out.append({'section': title, 'sentence': s, 'citation': f'[{next(iter(ns))}]', 'markers': [w for _, w in mk]}); break
    return out


def problems(md, lang=None):
    """Lines of check 14 (empty = OK): one heading line, then one line per flagged sentence."""
    if CFG.get('enabled') is False: return []
    f = flagged(md, lang)
    if not f: return []
    width = int(CFG.get('excerpt_chars') or 200)
    pb = [f'14 REPORT.md: {len(f)} sentence(s) compare, rank, count, exclude or report a search outcome across sources but cite a single '
          'source, which cannot say it: rewrite each one, with the fact of that source in its own sentence with its [n] and the comparison, '
          'count, exclusion or search outcome as your synthesis without [n] ("Of the studies read, ..."), or cite every source it compares']
    for x in f:
        s = x['sentence'] if len(x['sentence']) <= width else x['sentence'][:width - 1] + '…'
        pb.append(f'14 REPORT.md ({x["section"]}) {x["citation"]} "{", ".join(x["markers"])}": {s}')
    return pb


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args: print(__doc__); sys.exit(2)
    md = pathlib.Path(args[0]).read_text(encoding='utf-8', errors='replace')
    if '--json' in sys.argv: print(json.dumps(flagged(md), ensure_ascii=False, indent=1)); sys.exit(0)
    p = problems(md); print('\n'.join(p) if p else 'OK'); sys.exit(1 if p else 0)
