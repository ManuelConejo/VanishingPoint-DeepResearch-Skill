#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Conservative offline canonical bibliography URLs, configured in config.json.
No guessed truncation: an ambiguous token has no inferred address. finish_run
adds URLs atomically before fingerprints; read-only checks only warn.
An inferred URL says nothing about the existence or availability of a source.
"""
import json, os, pathlib, re, sys, tempfile
from urllib.parse import quote
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import report_lang as RL

RULES = json.loads((pathlib.Path(__file__).resolve().parent / 'config.json').read_text(encoding='utf-8'))['bibliography_links']['rules']
IDENT = re.compile(r'(?<![\w/.-])([a-z][a-z0-9]*):([^\s`]+)', re.I)
ENTRY = re.compile(r'^\[([0-9]{1,3})\] ')
URL = re.compile(r'https?://[^\s<>`]+')
AMBIGUOUS = re.compile(r'''[<>`?!:"'*\[\]\\&#%\x00-\x1f\x7f\ud800-\udfff\ufffd{}|]''')
BASIS = re.compile(r'\s+(?:\((?:(?:basis|read)\s*:?\s*)?(?:abstract|title)(?:\s+read)?\)\.?|basis:?\s*(?:abstract|title)\.?)\s*$', re.I)


def canonical_url(identifier, rules=None):
    """Complete, unambiguous configured identifier -> HTTPS URL; otherwise None."""
    kind, sep, value = identifier.partition(':')
    rule = (RULES if rules is None else rules).get(kind.lower()) if sep else None
    if not rule or kind != kind.lower() or not value or not value.isascii() or AMBIGUOUS.search(value): return None
    punctuation = rule.get('detachable_punctuation', '')
    if kind == 'doi' and value.endswith('..'): return None  # Only one sentence-final period is detachable.
    if punctuation: value = value.rstrip(punctuation)
    if not value or value[-1] in '.,;:_' + rule.get('ambiguous_endings', ''): return None
    depth = 0
    for char in value:
        if char == '(': depth += 1
        elif char == ')':
            depth -= 1
            if depth < 0: return None
    if depth: return None
    match = re.fullmatch(rule['pattern'], value, re.ASCII)
    if not match: return None
    fields = match.groupdict()
    for name, source in rule.get('fields', {}).items(): fields[name] = fields[source]
    for name, substitutions in rule.get('substitutions', {}).items():
        for pattern, replacement in substitutions: fields[name] = re.sub(pattern, replacement, fields[name])
    if any(part in ('.', '..') for v in fields.values() for part in v.split('/')): return None
    fields = {k: quote(v, safe=rule.get('safe', '')) for k, v in fields.items()}
    return rule['url'].format(**fields)


def _trim(value):
    """Legacy explicit-URL/export cleanup, never used to infer an identifier URL."""
    value = value.rstrip('.,;')
    for left, right in (('(', ')'), ('[', ']')):
        while value.endswith(right) and value.count(right) > value.count(left): value = value[:-1]
    return value


def physical_lines(text):
    """Split only at LF, keeping terminators and every other character intact."""
    parts = text.split('\n')
    return [part + '\n' for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def without_inline_code(text):
    """Mask paired backtick runs of equal length, preserving token offsets."""
    runs = list(re.finditer(r'`+', text))
    spans = []; index = 0
    while index < len(runs):
        opening = runs[index]
        prefix = text[:opening.start()]
        if (len(prefix) - len(prefix.rstrip('\\'))) % 2:
            index += 1; continue
        closing = next((j for j in range(index + 1, len(runs))
                        if len(runs[j][0]) == len(opening[0])), None)
        if closing is None:
            index += 1; continue
        spans.append((opening.start(), runs[closing].end()))
        index = closing + 1
    for start, end in reversed(spans):
        text = text[:start] + re.sub(r'[^\n]', ' ', text[start:end]) + text[end:]
    return text


def identifier_matches(text):
    """Raw token spans and decisions outside explicit URLs and inline code."""
    urls = [(m.start(), m.end()) for m in URL.finditer(text)]
    for m in IDENT.finditer(without_inline_code(text)):
        if any(a <= m.start() < b for a, b in urls): continue
        ident = m.group(0)
        start, end = m.span()
        bounded = (not start or text[start - 1] == ' ') and (end == len(text) or text[end] in ' \r\n')
        punctuation = RULES.get(m.group(1).lower(), {}).get('detachable_punctuation', '')
        url = canonical_url(ident) if bounded else None
        if url and punctuation: end -= len(ident) - len(ident.rstrip(punctuation))
        yield start, end, ident, url


def entry_lines(md):
    """Strict unindented entry starts, one physical line; never join continuations."""
    inside = False; fence = None; comment = False
    for index, line in enumerate(physical_lines(md)):
        if fence:
            if re.match(r'^[ \t]*' + re.escape(fence[0]) + '{' + str(len(fence)) + r',}[ \t]*(?:\r?\n)?$', line): fence = None
            continue
        mark = re.match(r'^[ \t]*(?:(?:[-+*]|[0-9]+[.)])[ \t]+)*(`{3,}|~{3,})', line)
        if mark and not comment: fence = mark[1]; continue
        if comment or '<!--' in line:
            for mark in re.findall(r'<!--|-->', line):
                if mark == '<!--': comment = True
                elif comment: comment = False
            continue
        heading = re.match(r'^ {0,3}(#{1,2})[ \t]+([^\n]+)', line)
        if heading:
            inside = heading[1] == '##' and RL.canonical(re.sub(r'[ \t]+#+[ \t]*$', '', heading[2]).strip()) == 'Bibliography'
        elif inside and (entry := ENTRY.match(line)):
            yield index, int(entry[1]), line


def entry_decisions(md):
    """Shared inference decision; any adjacent nonblank continuation rejects the entry."""
    lines = physical_lines(md)
    for index, n, line in entry_lines(md):
        following = lines[index + 1] if index + 1 < len(lines) else ''
        single = not following.strip() or (not following.startswith((' ', '\t')) and
                 (ENTRY.match(following) or re.match(r'^#{1,2} ', following)))
        matches = list(identifier_matches(line)) if single else None
        # One document = one identifier: a second configured identifier (e.g. cited in the title) makes the entry ambiguous.
        if matches and sum(1 for _, _, ident, _ in matches if ident.partition(':')[0].lower() in RULES) > 1: matches = None
        yield index, n, line, matches


def _absent(line, matches):
    urls = {_trim(m.group(0).rstrip('"\'')) for m in URL.finditer(line)}
    return [(i, u) for _, _, i, u in matches or () if u and u not in urls]


def missing(md):
    return [f'11 REPORT.md: bibliography [{n}] {i} missing canonical URL <{u}>; finish_run.py adds it at closure'
            for _, n, line, matches in entry_decisions(md) for i, u in dict.fromkeys(_absent(line, matches))]


def warnings(md):
    out = missing(md)
    for _, n, line, matches in entry_decisions(md):
        tokens = list(identifier_matches(line)) if matches is None else matches
        configured = [(ident, url) for _, _, ident, url in tokens
                      if ident.partition(':')[0].lower() in RULES]
        if configured and (matches is None or any(url is None for _, url in configured)):
            out.append(f'11 REPORT.md: bibliography [{n}]: address not deducible (unsupported entry shape, ambiguous or invalid configured identifier); no address inferred')
    return list(dict.fromkeys(out))


def enrich(md):
    lines = physical_lines(md)
    for index, _, line, matches in entry_decisions(md):
        absent = list(dict.fromkeys(u for _, u in _absent(line, matches)))
        if not absent: continue
        content = line.rstrip('\r\n'); ending = line[len(content):]
        basis = BASIS.search(content)
        pos = basis.start() if basis else len(content.rstrip())
        lines[index] = content[:pos] + ''.join(' <' + u + '>' for u in absent) + content[pos:] + ending
    return ''.join(lines)


def enrich_file(path):
    path = pathlib.Path(path)
    if not path.is_file(): return False
    before = path.read_bytes()
    # Preserve invalid bytes; such bytes inside an identifier forbid inference.
    after = enrich(before.decode('utf-8', errors='surrogateescape')).encode('utf-8', errors='surrogateescape')
    if after == before: return False
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.' + path.name + '.', delete=False) as f:
            temp = pathlib.Path(f.name)
            os.fchmod(f.fileno(), path.stat().st_mode & 0o777)
            f.write(after); f.flush(); os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None: temp.unlink(missing_ok=True)
    return True
