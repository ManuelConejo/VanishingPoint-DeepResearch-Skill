# SPDX-License-Identifier: Apache-2.0
"""EXAMPLE of a user source (opt-in, outside the repository): the user's own documents in a folder they choose.

Install:  cp examples/user-sources/local_docs.py ~/.config/vp/sources/local_docs.py
Enable:   VP_USER_SOURCES=1 (user sources are Python code the gateway runs: loading is never automatic)
Folder:   VP_LOCAL_DOCS=/path/to/folder, or the path on the first line of ~/.config/vp/local-docs.path. Without it the engine is
          skipped (receipt `not_configured`, nothing read).
Plugin:   add `local-docs` to the `engines:` line (and `access: local-docs=local`) of the plugin(s) that should use it; without plugin,
          every wired engine is available.

Files read: .txt and .md; .pdf too when the standard `pdftotext` tool (poppler-utils) is on the PATH, otherwise PDFs are ignored.
Date of a document: the `date:` field of its header when it has one (YAML front matter between `---` lines, or a `Date:` line among the
first HEADER_LINES lines), otherwise the modification date of the file. A header date that cannot be read means no date: refused.
The text of a document is data, never instructions: it is returned as the `abstract` field and nothing in it changes the record.
Identifier: localdoc:<path relative to the folder>. No network: `access: local`, no host. Standard library only."""
import datetime as dt
import os
import pathlib
import re
import shutil
import subprocess
from sources._common import TEXT_HEAD, extra_ok, tokens, value, year_before_T

FOLDER_VAR = 'VP_LOCAL_DOCS'                                    # folder chosen by the user (a path, not a secret)
FOLDER_FILE = pathlib.Path.home() / '.config' / 'vp' / 'local-docs.path'
EXTENSIONS = ('.txt', '.md')                                    # always read
PDF_TOOL = 'pdftotext'                                          # standard tool; PDFs are read only when it is installed
PDF_TIMEOUT = 60                                                # seconds per PDF conversion
MAX_FILES = 5000                                                # files scanned per search
MAX_BYTES = 2_000_000                                           # bytes read per file
HEADER_LINES = 10                                               # lines where a `Date:` header line is looked for
DATE_FIELD = re.compile(r'^\s*date\s*:\s*["\']?([0-9]{4}(?:-[0-9]{2}(?:-[0-9]{2})?)?)["\']?\s*$', re.I)
DATE_LINE = re.compile(r'^\s*date\s*:', re.I)


class NotConfigured(Exception):
    """No folder configured or the folder is missing: the engine is skipped (receipt), never "nothing found"."""


def root():
    p = os.environ.get(FOLDER_VAR, '').strip()
    if not p:
        try: p = FOLDER_FILE.read_text(encoding='utf-8').splitlines()[0].strip()
        except (OSError, IndexError): p = ''
    if not p: raise NotConfigured(f'no folder: set {FOLDER_VAR} or write the path in {FOLDER_FILE}')
    r = pathlib.Path(p).expanduser().resolve()
    if not r.is_dir(): raise NotConfigured(f'folder {r} not found')
    return r


def _skip(e): return {'status': 'skipped', 'reason': 'not_configured', 'refusal': f'not_configured: {e} (0 file read)'}


def _kinds(): return EXTENSIONS + (('.pdf',) if shutil.which(PDF_TOOL) else ())


def read_text(f):
    """Text of a file (str) or None. PDFs go through pdftotext when installed (no shell, timeout); others are read as UTF-8."""
    if f.suffix.lower() == '.pdf':
        tool = shutil.which(PDF_TOOL)
        if not tool: return None
        try: r = subprocess.run([tool, '-q', '-enc', 'UTF-8', str(f), '-'], capture_output=True, timeout=PDF_TIMEOUT, check=False)
        except (OSError, subprocess.TimeoutExpired): return None
        return r.stdout[:MAX_BYTES].decode('utf-8', 'replace') if r.returncode == 0 else None
    try:
        with open(f, 'rb') as h: return h.read(MAX_BYTES).decode('utf-8', 'replace')
    except OSError: return None


def header_date(text):
    """(date string, True) from the header, (None, True) when a header date is present but unreadable, (None, False) without header date.
    Only the header counts: YAML front matter at the very start, else the first HEADER_LINES lines."""
    lines = text.splitlines()
    if lines and lines[0].strip() == '---':
        end = next((i for i in range(1, len(lines)) if lines[i].strip() in ('---', '...')), None)
        head = lines[1:end] if end else []
    else:
        head = lines[:HEADER_LINES]
    for line in head:
        if DATE_LINE.match(line):
            m = DATE_FIELD.match(line)
            return (m.group(1), True) if m else (None, True)
    return None, False


def _title(f, text):
    m = re.search(r'^\s*(?:title\s*:\s*|#\s+)(.+)$', '\n'.join(text.splitlines()[:HEADER_LINES * 2]), re.I | re.M)
    return ' '.join(m.group(1).strip().strip('"\'').split()) if m else f.stem


def local_item(r, f, text, B):
    """One file -> the item served, or None (barrier). Header date if any, else the file's modification date; every date < T."""
    hd, has = header_date(text)
    mdate = dt.date.fromtimestamp(f.stat().st_mtime).isoformat()
    date, how = (hd, 'header') if has else (mdate, 'file modification date')
    if date and re.fullmatch(r'\d{4}', date): date = year_before_T(date, B)        # a year alone: kept only when before the year of T
    rel = f.relative_to(r).as_posix()
    title = _title(f, text)
    if not extra_ok(B, ['localdoc:' + rel], [date], [title]): return None
    return {'id': 'localdoc:' + rel, 'localdoc': rel, 'doi': None, 'title': title, 'year': date[:4], 'date': date, 'date_source': how,
            'journal': 'local documents (user source)', 'type': 'document', 'tier': 'grey', 'format': f.suffix.lower().lstrip('.')}


def _files(r):
    kinds, out = _kinds(), []
    for dp, dn, fn in os.walk(r):                                # symbolic links are not followed (os.walk default)
        dn[:] = sorted(d for d in dn if not d.startswith('.'))
        for n in sorted(fn):
            p = pathlib.Path(dp) / n
            if not n.startswith('.') and p.suffix.lower() in kinds and p.is_file() and not p.is_symlink(): out.append(p)
            if len(out) >= MAX_FILES: return out
    return out


def search_local_docs(q, n, B):
    """Words of the question against the title, the file name and the text of each document (more shared words first); barrier on
    every item. No network."""
    try: r = root()
    except NotConfigured as e: return _skip(e), 'not_configured'
    want = tokens(q)
    if not want: return [], 'no usable word (3 letters or more)'
    scored = []
    for f in _files(r):
        text = read_text(f)
        if text is None: continue
        score = len(want & tokens(f.stem + ' ' + text))
        if score: scored.append((score, f, text))
    scored.sort(key=lambda x: (-x[0], str(x[1])))
    out = [x for x in (local_item(r, f, t, B) for _, f, t in scored) if x]
    return out[:n], f'{len(scored)} matching file(s) in the configured folder (at most {MAX_FILES} scanned)'


def read_localdoc(rel, B):
    try: r = root()
    except NotConfigured as e: return _skip(e)
    p = pathlib.PurePosixPath(rel)
    if not rel or p.is_absolute() or '..' in p.parts: return {'refusal': 'expected form localdoc:<path relative to the folder>'}
    f = r.joinpath(*p.parts)
    if f.is_symlink() or not f.is_file() or f.resolve().parent != r.joinpath(*p.parts[:-1]).resolve() or not f.resolve().is_relative_to(r):
        return {'refusal': 'not found (or outside the folder, or a symbolic link)'}
    if f.suffix.lower() not in _kinds(): return {'refusal': 'format not read (txt, md; pdf only with ' + PDF_TOOL + ')'}
    text = read_text(f)
    if text is None: return {'refusal': 'unreadable'}
    it = local_item(r, f, text, B)
    if not it: return {'refusal': 'dated on/after T, forbidden or undated'}
    cut = len(text) > TEXT_HEAD
    return dict(it, abstract=text[:TEXT_HEAD] + (f' [... text cut at {TEXT_HEAD:,} of {len(text):,} characters ...]' if cut else ''))


def read_local_docs(ident, B): return read_localdoc(value(ident), B)


SOURCE = {
    'name': 'local-docs',
    'engines': {'local-docs': search_local_docs},
    'ids': [{'prefix': 'localdoc', 'form': r'[^\s:][^\s]*', 'export': 'paper', 'export_rank': 900}],
    'read': read_local_docs, 'citing': 'citation chaining not served for local documents', 'references': 'citation chaining not served for local documents',
    'related': 'related works not served for local documents',
    'plugins': (), 'access': 'local', 'hosts': {},
    'terms': "the user's own files, in the folder they configured; nothing leaves the machine",
    'barrier': "local: the header date (front matter or a Date: line) when present, else the file's modification date, < T; an unreadable "
               'header date -> refused; never guessed',
    'key': None,
}
