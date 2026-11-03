#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Figures of a FOUND claim against the fragments that support it (tools/verifier.py, config verifier.numbers). Stdlib only, no model.

A figure of the claim is supported when a figure of the fragments equals it at the claim's precision (42 % ~ 41.87; 0.42 ~ 0.4187),
also after the percentage <-> proportion conversion (42 % ~ 0.4187). A decimal comma is read as a decimal point; 1,234 / 1.234 is
read both ways (thousands or decimal). Skipped: single-digit integers (counts, list numbers, often written as words), years 1900-2099
(publication dates rarely sit in the cited passage), figures glued to letters (GPT-4, A100, Llama-3-8B) and labels, a figure right
after a capitalised word (AIME 24, Table 12, Qwen 2.5). The claim's figures must be
SHOWN by the fragments (ROLE.md: the fragments are the evidence); a figure found elsewhere in the source is still reported.

Command line: numbers_check.py "<claim>" "<fragment>" ...   -> the problems as JSON, exit 1 when there is one.
"""
import json, re, sys, unicodedata

LABEL = re.compile(r'(?:^|[^\w])[A-Z][^\W\d_]*[ \u00a0]$')
NUM = re.compile(r'(?<![\w.,])(?<![^\W\d_]-)(\d+(?:[.,]\d+)*)(?=$|[^\w]|[x×](?!\w))')


def readings(tok):
    """Values of a number token, each as (value, decimals of the written form)."""
    out = set()
    if re.fullmatch(r'\d{1,3}(?:([.,])\d{3})+', tok) and len(set(re.findall(r'[.,]', tok))) == 1:
        out.add((float(re.sub(r'[.,]', '', tok)), 0))               # thousands separator
    if tok.count('.') + tok.count(',') <= 1:
        t = tok.replace(',', '.')
        out.add((float(t), len(t.split('.')[1]) if '.' in t else 0))
    return out


def figures(text):
    """(token, readings) of the figures of a text, in order (NFKC first: full-width digits, ligatures)."""
    out = []
    t = unicodedata.normalize('NFKC', text or '')
    for m in NUM.finditer(t):
        if LABEL.search(t[max(0, m.start() - 24):m.start()]): continue
        r = readings(m.group(1))
        if r: out.append((m.group(1), r))
    return out


def skipped(r):
    return all(d == 0 and (v < 10 or 1900 <= v <= 2099) for v, d in r)


def supported(r, values):
    for c, d in r:
        tol = 0.5 * 10 ** -d + 1e-9
        if any(abs(s * k - c) <= tol for s in values for k in (1, 100, 0.01)): return True
    return False


def problems(claim, fragments):
    """Messages for the figures of the claim that no fragment shows; [] when every figure is shown (or the claim has none)."""
    values = {v for f in fragments or [] for _, r in figures(f) for v, _ in r}
    out = []
    for tok, r in figures(claim):
        if skipped(r) or supported(r, values): continue
        msg = f'figure {tok!r} of the claim not shown by the fragments'
        if msg not in out: out.append(msg)
    return out


if __name__ == '__main__':
    if len(sys.argv) < 2: print(__doc__); sys.exit(2)
    p = problems(sys.argv[1], sys.argv[2:])
    print(json.dumps(p, ensure_ascii=False)); sys.exit(1 if p else 0)
