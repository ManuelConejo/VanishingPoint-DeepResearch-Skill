#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Creates the working directory of a question when the instruction names none (SKILL.md section 0 "Working directory").
Standard library, no network, no model. Name: <prefix>-<YYYY-MM-DD>-<short ASCII subject>/ in the current directory (or --base), e.g.
vp-2026-10-29-jeune-intermittent-hba1c-diabete/; never an existing directory: the creation is atomic and a taken name gets -2, -3...
It also writes state/run-start.json (question, language, creation time: the start of the run for the duration of SUMMARY.md); nothing else.
Usage: new_run.py "<question>" [--base DIR] [--date YYYY-MM-DD] [--json]
Prints the absolute path of the new directory (first line), then `language: <code>` (tools/report_lang.py). Exit 0; 2 on an error.
Settings: tools/config.json `new_run` (prefix, slug_words, slug_chars, extra_stopwords).
Import: slug(question) -> str; create(question, base='.', date=None) -> pathlib.Path."""
import argparse, datetime as dt, json, os, pathlib, re, sys, unicodedata
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P))
import report_lang as RL   # noqa: E402

CFG = json.loads((P / 'config.json').read_text(encoding='utf-8')).get('new_run') or {}
PREFIX = str(CFG.get('prefix', 'vp')); WORDS = int(CFG.get('slug_words', 5)); CHARS = int(CFG.get('slug_chars', 40))


def _ascii(t):
    t = unicodedata.normalize('NFKD', str(t or '')).replace('ß', 'ss').replace('œ', 'oe').replace('æ', 'ae')
    return ''.join(c for c in t if not unicodedata.combining(c)).encode('ascii', 'ignore').decode().lower()


STOP = {_ascii(w) for L in RL.LANGS.values() for w in L['stop']} | {_ascii(w) for w in CFG.get('extra_stopwords') or []}


def slug(question):
    """Short ASCII subject: the first content words of the question (no stopword, no one-letter word, no year), hyphenated."""
    words = [w for w in re.findall(r'[a-z0-9]+', _ascii(question)) if len(w) > 1 and w not in STOP and not re.fullmatch(r'(1[89]|20)\d\d', w)]
    out = ''
    for w in words[:WORDS]:
        cand = f'{out}-{w}' if out else w
        if len(cand) > CHARS: break
        out = cand
    return out or (words[0][:CHARS] if words else 'question')


def create(question, base='.', date=None):
    base = pathlib.Path(base).resolve()
    date = date or dt.datetime.now(dt.timezone.utc).date().isoformat()
    stem = f'{PREFIX}-{date}-{slug(question)}'
    for i in range(1, 10000):
        d = base / (stem if i == 1 else f'{stem}-{i}')
        try: d.mkdir()                                   # atomic: an existing directory (or file) is never reused
        except FileExistsError: continue
        (d / 'state').mkdir()
        (d / 'state' / 'run-start.json').write_text(json.dumps({'question': question, 'language': RL.detect(question),
                                                               'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')},
                                                              ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        return d
    raise RuntimeError(f'no free name for {stem} under {base}')


def main(argv=None):
    ap = argparse.ArgumentParser(description='Create the working directory of a question (never an existing one).')
    ap.add_argument('question', nargs='+'); ap.add_argument('--base', default='.'); ap.add_argument('--date'); ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    if a.date and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', a.date): print(f'new_run.py: --date expects YYYY-MM-DD: {a.date!r}', file=sys.stderr); return 2
    if not pathlib.Path(a.base).is_dir(): print(f'new_run.py: not a directory: {a.base!r}', file=sys.stderr); return 2
    q = ' '.join(a.question)
    try: d = create(q, a.base, a.date)
    except OSError as e: print(f'new_run.py: {type(e).__name__}: {e}', file=sys.stderr); return 2
    if a.json: print(json.dumps({'dir': str(d), 'language': RL.detect(q)}, ensure_ascii=False)); return 0
    print(d); print(f'language: {RL.detect(q)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
