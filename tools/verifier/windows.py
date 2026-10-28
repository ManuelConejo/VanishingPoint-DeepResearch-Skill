#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Claim windows for the level-1 verifier: the few spans of a source text that matter to the claims checked against it, found by
deterministic code (no model). Standard library only, offline.

A window is always an exact substring of the retrieved text: `text[start:end]`, never rewritten, so a fragment the verifier copies from
a window is found as is by citation_check.py and by tools/passages.py in the full text kept under DIR/sources/<KEY>/source.txt.

How the spans are chosen, for each claim of a source:
  - candidate windows of `window_chars` characters every `window_chars // 2` characters (half-window stride: any span of at most
    window_chars / 2 characters lies whole inside one candidate, so a fragment of up to 300 characters, the ROLE.md upper bound, is never
    cut when window_chars >= 600);
  - each candidate is scored with BM25 against the claim (words and numbers; numbers normalised, 0,42 = 0.42, and counted
    `number_weight` times, since a figure is the element most often distorted);
  - for each number of the claim found in the text, the best candidate that contains it is taken first (a figure present in the source is
    always shown to the verifier), then the best remaining candidates, `windows_per_claim` in all;
  - the head of the text (`head_chars`: title, abstract) is always added.
The windows of all the claims of a source are merged (overlaps joined). A source no longer than what one claim may receive
(head_chars + windows_per_claim x window_chars) is sent whole: windowing it saves nothing.

Import: select(text, claims, params) -> {'spans': [(start, end)], 'whole': bool, 'per_claim': {...}, 'chars_available', 'chars_sent'};
        render(text, spans) -> the text written to the verifier's working copy of source.txt (windows separated by marker lines)."""
import hashlib, math, re, unicodedata

DEFAULTS = {'mode': 'windows', 'window_chars': 1000, 'windows_per_claim': 6, 'head_chars': 1500, 'number_weight': 2,
            'escalate_statuses': ['ABSENT', 'SOURCE-UNAVAILABLE'], 'escalation_max_chars': None}   # None: the caller's max_chars_per_call
WORD = re.compile(r'\d+(?:[.,]\d+)*|[^\W\d_]+', re.U)
NUM = re.compile(r'^\d+(?:[.,]\d+)*$')


def params(cfg=None):
    """Window parameters: DEFAULTS overridden by the config block (tools/config.json verifier.windows)."""
    p = dict(DEFAULTS)
    p.update({k: v for k, v in (cfg or {}).items() if k in DEFAULTS})
    for k in ('window_chars', 'windows_per_claim', 'head_chars', 'number_weight'): p[k] = max(0, int(p[k]))
    p['window_chars'] = max(2, p['window_chars']); p['windows_per_claim'] = max(1, p['windows_per_claim'])
    p['escalate_statuses'] = [str(x).upper() for x in (p['escalate_statuses'] or [])]
    if p['escalation_max_chars'] is not None: p['escalation_max_chars'] = int(p['escalation_max_chars'])
    if p['mode'] not in ('windows', 'whole'): raise ValueError(f"verifier.windows.mode: 'windows' or 'whole' expected, got {p['mode']!r}")
    return p


def num_forms(tok):
    """Normalised forms of a number token: decimal comma -> point; a thousands separator also gives the bare digits."""
    t = tok.replace(',', '.')
    out = {t}
    if re.fullmatch(r'\d{1,3}(?:\.\d{3})+', t): out.add(t.replace('.', ''))
    if re.fullmatch(r'\d+\.0+', t): out.add(t.split('.')[0])
    return out


def tokens(s):
    """Lower-cased words and normalised numbers of a text (NFKC first: ligatures, full-width digits)."""
    out = []
    for m in WORD.finditer(unicodedata.normalize('NFKC', s or '').lower()):
        w = m.group(0)
        if NUM.match(w): out.extend(sorted(num_forms(w)))
        elif len(w) > 1: out.append(w)
    return out


def claim_numbers(s):
    """Numbers of a claim, each as its set of forms, plus the percentage <-> proportion form (42 % <-> 0.42)."""
    out = []
    for m in WORD.finditer(unicodedata.normalize('NFKC', s or '').lower()):
        w = m.group(0)
        if not NUM.match(w): continue
        f = num_forms(w)
        for x in list(f):
            if re.fullmatch(r'0\.\d+', x): f.add(str(round(float(x) * 100, 10)).rstrip('0').rstrip('.'))
            elif re.fullmatch(r'\d{1,2}(?:\.\d+)?', x) and float(x) > 0: f.add(str(round(float(x) / 100, 10)))
        out.append(f)
    return out


def candidates(n, w):
    """Start offsets of the candidate windows of length w over a text of n characters, stride w // 2, last window flush with the end."""
    step = max(1, w // 2)
    starts = list(range(0, max(1, n - w + 1), step))
    if n > w and starts[-1] != n - w: starts.append(n - w)
    return starts


def snap(text, a, b, reach):
    """Move a window's ends out to the nearest whitespace (at most `reach` characters), so that no word or number is cut in two."""
    if a > 0 and not text[a - 1].isspace():
        i = max((text.rfind(c, max(0, a - reach), a) for c in ' \n\t'), default=-1)
        if i >= 0: a = i + 1
    if b < len(text) and not text[b].isspace():
        js = [j for j in (text.find(c, b, min(len(text), b + reach)) for c in ' \n\t') if j >= 0]
        if js: b = min(js)
    return a, b


def merge(spans):
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]: out[-1] = (out[-1][0], max(out[-1][1], b))
        else: out.append((a, b))
    return out


def select(text, claims, p):
    """text: the retrieved source text; claims: list of {'id', 'text'} checked against it; p: params(). -> spans and trace."""
    n = len(text); w = p['window_chars']; k = p['windows_per_claim']; head = min(p['head_chars'], n)
    base = {'chars_available': n}
    if p['mode'] == 'whole' or n <= p['head_chars'] + k * w:
        return dict(base, spans=[(0, n)] if n else [], whole=True, reason='mode whole' if p['mode'] == 'whole' else 'short source', chars_sent=n, per_claim={})
    starts = candidates(n, w)
    docs = [tokens(text[s:s + w]) for s in starts]
    df = {}
    for d in docs:
        for t in set(d): df[t] = df.get(t, 0) + 1
    N = len(docs); avg = sum(map(len, docs)) / max(1, N)
    tfs = []
    for d in docs:
        tf = {}
        for t in d: tf[t] = tf.get(t, 0) + 1
        tfs.append((tf, len(d)))
    k1, bb = 1.5, 0.75                                               # BM25 standard constants (Robertson & Zaragoza 2009)
    spans = [(0, head)] if head else []
    per = {}
    for c in claims:
        q = {}
        for t in tokens(c.get('text', '')): q[t] = q.get(t, 0) + (p['number_weight'] if NUM.match(t) else 1)
        def score(i):
            tf, L = tfs[i]
            return sum(wq * math.log(1 + (N - df[t] + .5) / (df[t] + .5)) * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - bb + bb * L / avg))
                       for t, wq in q.items() if t in tf)
        sc = [score(i) for i in range(N)]
        order = sorted(range(N), key=lambda i: (-sc[i], i))
        chosen = []
        nums = claim_numbers(c.get('text', ''))
        found_nums = 0
        for forms in nums:                                           # a figure of the claim present in the text is always shown
            hit = [i for i in order if forms & set(tfs[i][0])]
            if hit:
                found_nums += 1
                if hit[0] not in chosen and len(chosen) < k: chosen.append(hit[0])
        for i in order:
            if len(chosen) >= k or sc[i] <= 0: break
            if i not in chosen: chosen.append(i)
        cs = [snap(text, starts[i], min(n, starts[i] + w), w // 2) for i in chosen]
        spans += cs
        per[str(c.get('id'))] = {'windows': len(cs), 'numbers': len(nums), 'numbers_in_text': found_nums,
                                 'matched': any(sc[i] > 0 for i in chosen)}
    spans = merge(spans)
    sent = sum(b - a for a, b in spans)
    return dict(base, spans=spans, whole=sent >= n, reason='windows cover the text' if sent >= n else 'windows', chars_sent=sent, per_claim=per)


def nonce(text):
    """Marker code of a source: derived from the text itself, so a marker line forged inside the source cannot carry it."""
    return hashlib.sha256((text or '').encode('utf-8', 'replace')).hexdigest()[:10]


def render(text, spans):
    """Working copy of source.txt for a windowed source: a header line, then each window preceded by its own marker line.
    Every window body is text[a:b] exactly; marker lines start with '[VP window <code>' and are not source text."""
    if len(spans) == 1 and spans[0] == (0, len(text)): return text
    code = nonce(text); n = len(text); sent = sum(b - a for a, b in spans)
    out = [f'[VP window {code}] EXCERPTS of a longer source: {len(spans)} windows, {sent} of {n} characters, chosen by code for the claims. '
           f'Lines starting with "[VP window {code}" are not source text; never copy a fragment across two windows.']
    for i, (a, b) in enumerate(spans, 1):
        out.append(f'[VP window {code} {i}/{len(spans)}: characters {a}-{b} of {n}]')
        out.append(text[a:b])
    return '\n'.join(out) + '\n'


def bodies(rendered, text):
    """Inverse of render for the tests and the measure: the window bodies of a rendered copy, found through the real marker code only."""
    code = nonce(text)
    if not rendered.startswith(f'[VP window {code}]'): return [rendered]
    out = []
    for m in re.finditer(rf'^\[VP window {code} \d+/\d+: characters (\d+)-(\d+) of \d+\]$', rendered, re.M):
        a, b = int(m.group(1)), int(m.group(2)); out.append(text[a:b])
    return out
