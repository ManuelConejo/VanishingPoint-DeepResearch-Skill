#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Export of a run's final report (SKILL.md section 8): REPORT.md -> REPORT.html, always; -> REPORT.pdf with --pdf. Standard library,
no network, installs nothing. The HTML is one self-contained file (inline CSS, no script, no external resource): a small Markdown
converter for the subset VP reports use (headings, paragraphs, bold/italics, inline code, fenced code, lists, tables, block quotes,
links), each [n] linked to its bibliography entry (with back-links), doi:/pmid:/arxiv: identifiers and http(s) URLs clickable,
a header taken from card.json / run.json / result.json / verdicts.json / scope.md when they give it, print CSS (A4, page breaks before
the bibliography and the appendix). Every character of the report is HTML-escaped (the text comes from sources); a link is kept
only for http, https, mailto or an in-page #anchor, images become their alt text.
Cited passages (when the run has verdicts.json): under each bibliography entry, the claims checked against it, each with the exact passage
of its source (tools/passages.py: located from the verifier's machine-checked fragments in DIR/sources/<KEY>/source.txt, never written by
a model; escaped, the verified fragment highlighted) and its origin (identifier, full text with version or record + abstract), or the reason
why no passage was verified. REPORT.md itself is not changed.
PDF: the first converter found, in this order: WeasyPrint (Python module, then `weasyprint` command), Chromium/Chrome headless
(`--no-sandbox` only on a retry inside a container, as root or when the sandbox could not start), `wkhtmltopdf`, `pandoc` with a PDF engine found on PATH.
None found or all failed: the HTML stays, one line says so, exit 0 (the HTML prints to PDF from any browser).
Optional appendices (never by default): --prisma adds the PRISMA 2020 flow diagram of tools/prisma.py (inline SVG, built from the run's
records at export time); --followups adds the follow-up questions of tools/followups.py (fixed templates filled from the run's files).
Usage: export_report.py RUN_DIR [--pdf] [--out DIR] [--prisma] [--followups]     Exit: 0 written; 2 no REPORT.md.
Import: render(md, meta, extra=[(id, title, html)]) -> str; meta(dir) -> [(k, v)]; extras(dir, prisma, followups) -> [(id, title, html)]."""
import argparse, datetime as dt, html, importlib, importlib.util, json, os, pathlib, re, shutil, subprocess, sys, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import report_lang as RL   # noqa: E402  (titles of the eight sections in every language of the table)

TIMEOUT = 180  # seconds per converter attempt
PAGE_BREAK = {'Bibliography', 'Methodology Appendix'}  # level-2 sections that start a new printed page (canonical titles, any language: report_lang)
FINDING_SLUG = re.compile(r'(?:' + '|'.join(map(re.escape, RL.finding_words())) + r') (\d+)\b')
SAFE_URL = re.compile(r'^(https?://|mailto:)[^\s]+$|^#[\w.:-]+$', re.I)
IDLINK = {'doi': 'https://doi.org/{}', 'pmid': 'https://pubmed.ncbi.nlm.nih.gov/{}/', 'arxiv': 'https://arxiv.org/abs/{}',
          'pmcid': 'https://www.ncbi.nlm.nih.gov/pmc/articles/{}/'}
ID_RE = re.compile(r'\b(doi|pmid|arxiv|pmcid):\s?(10\.\d{4,9}/[^\s<>]+|PMC\d+|\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[A-Z]{2})?/\d{7}|\d+)', re.I)
URL_RE = re.compile(r'https?://(?:(?!&quot;|&lt;|&gt;|&#x27;)[^\s])+')
TRAIL = '.,;:!?)]\''
CITE_RE = re.compile(r'\[(\d{1,3}(?:\s*[,;]\s*\d{1,3})*)\](?!\()')
BIB_LINE = re.compile(r'^\s*\[(\d{1,3})\]\s*(.*)$')

CSS = """
:root{color-scheme:light}
html{background:#fff}
body{margin:0 auto;max-width:46rem;padding:2.5rem 1.25rem 4rem;background:#fff;color:#1d1d1f;font:16px/1.6 Georgia,"Times New Roman","DejaVu Serif",serif;
 text-rendering:optimizeLegibility;hyphens:manual;overflow-wrap:break-word}
h1,h2,h3,h4,h5,h6,.meta,nav,table,.bib .n{font-family:"Helvetica Neue",Arial,"Liberation Sans","DejaVu Sans",sans-serif}
h1{font-size:1.75rem;line-height:1.25;margin:0 0 1rem;letter-spacing:-.01em}
h2{font-size:1.3rem;line-height:1.3;margin:2.4rem 0 .8rem;padding-bottom:.25rem;border-bottom:1px solid #d9d9de}
h3{font-size:1.07rem;line-height:1.35;margin:1.8rem 0 .6rem}
h4,h5,h6{font-size:1rem;margin:1.4rem 0 .5rem}
h2,h3,h4{break-after:avoid;page-break-after:avoid}
p{margin:0 0 .85rem;text-align:left}
a{color:#1a4f9c;text-decoration:none}
a:hover{text-decoration:underline}
code{font:.86em/1.4 "SFMono-Regular",Menlo,Consolas,"DejaVu Sans Mono",monospace;background:#f3f3f6;padding:.05em .3em;border-radius:3px;overflow-wrap:anywhere}
pre{background:#f6f6f8;border:1px solid #e3e3e8;border-radius:4px;padding:.7rem .9rem;overflow-x:auto;white-space:pre-wrap;break-inside:avoid}
pre code{background:none;padding:0}
blockquote{margin:0 0 1rem;padding:.2rem 1rem;border-left:3px solid #c9c9d1;color:#45454d}
ul,ol{margin:0 0 .9rem;padding-left:1.5rem}
li{margin:.2rem 0}
hr{border:0;border-top:1px solid #d9d9de;margin:2rem 0}
.tw{overflow-x:auto;margin:0 0 1rem}
table{border-collapse:collapse;width:100%;font-size:.86rem;line-height:1.4}
th,td{border:1px solid #d6d6dc;padding:.35rem .5rem;vertical-align:top;text-align:left}
th{background:#f1f1f5;font-weight:600}
thead{display:table-header-group}
tr{break-inside:avoid;page-break-inside:avoid}
.meta{margin:0 0 1.6rem;padding:.8rem 1rem;background:#f6f7f9;border:1px solid #e2e4e9;border-radius:6px;font-size:.84rem;line-height:1.45}
.meta dl{display:grid;grid-template-columns:max-content 1fr;gap:.25rem 1rem;margin:0}
.meta dt{color:#5b5b66;font-weight:600}
.meta dd{margin:0}
.pre{color:#55555f;font-size:.92rem}
nav{font-size:.86rem;margin:0 0 2rem;line-height:1.45}
nav .t{font-weight:600;color:#5b5b66;margin-bottom:.3rem}
nav ol{margin:0;padding-left:1.3rem}
nav ol ol{list-style:none;padding-left:.6rem}
a.cite{font-size:.82em;white-space:nowrap}
.bib p{padding-left:2.6rem;text-indent:-2.6rem;margin:0 0 .55rem;font-size:.92rem;line-height:1.45;overflow-wrap:anywhere;hyphens:none}
.bib .n{display:inline-block;min-width:2.6rem;text-indent:0;font-weight:600;font-size:.86em;color:#45454d}
.bib .back{font-size:.8em;margin-left:.3rem}
.bib p:target{background:#fff6d6}
.cp{margin:-.2rem 0 .9rem 2.6rem;font-size:.86rem;line-height:1.45}
.cp .c{margin:.45rem 0 .15rem;color:#2d2d33}
.cp .id{font-family:"Helvetica Neue",Arial,"DejaVu Sans",sans-serif;font-weight:600;font-size:.8em;color:#5b5b66;margin-right:.3rem}
.cp .st{font-family:"Helvetica Neue",Arial,"DejaVu Sans",sans-serif;font-size:.72em;font-weight:600;padding:0 .3em;border-radius:3px;background:#e9f3ea;color:#1f5f2a;margin-right:.35rem}
.cp .st.d{background:#fbeee0;color:#7a4300}
.cp .st.n{background:#efeff3;color:#55555f}
.cp blockquote{margin:.15rem 0 .1rem;padding:.25rem .7rem;border-left:3px solid #8fb79a;background:#f7faf7;color:#1d1d1f;font-style:normal;overflow-wrap:anywhere}
.cp mark{background:#fff0b3;color:inherit;padding:0}
.cp .o,.cp .none{font-size:.92em;color:#66666f}
.cp .none{font-style:italic}
footer{margin-top:3rem;font-size:.78rem;color:#77777f;border-top:1px solid #e3e3e8;padding-top:.6rem}
@page{size:A4;margin:20mm 18mm 22mm 18mm;@bottom-center{content:counter(page) " / " counter(pages);font:9pt Arial,"DejaVu Sans",sans-serif;color:#777}}
@media print{
 body{max-width:none;padding:0;font-size:10.5pt;line-height:1.5}
 h1{font-size:19pt}h2{font-size:14pt;margin-top:1.6rem}h3{font-size:11.5pt}
 h2.pb{break-before:page;page-break-before:always;margin-top:0}
 p,li{orphans:3;widows:3}
 .bib .back,nav .noprint{display:none}
 a{color:#1a3f7a}
 .tw{overflow:visible}
 pre{white-space:pre-wrap}
}
"""


# ---------- inline ----------
class Inline:
    """Inline renderer; escapes first, then builds every tag through a placeholder so that no later rule rewrites an attribute."""
    def __init__(self, refs):
        self.refs, self.cites, self.store = refs, {}, []   # refs: bibliography numbers; cites: n -> [anchor ids]

    def stash(self, s):
        self.store.append(s); return f'\x00{len(self.store) - 1}\x00'

    def link(self, url, label):
        url = html.unescape(url).strip()
        return self.stash(f'<a href="{html.escape(url, quote=True)}">{label}</a>') if SAFE_URL.match(url) else label

    def cite(self, m, anchor=True):
        nums = [int(x) for x in re.split(r'\s*[,;]\s*', m.group(1))]
        if not all(n in self.refs for n in nums): return m.group(0)
        out = []
        for n in nums:
            if anchor:
                cid = f'cite-{n}-{len(self.cites.setdefault(n, [])) + 1}'; self.cites[n].append(cid)
                out.append(f'<a class="cite" id="{cid}" href="#ref-{n}">[{n}]</a>')
            else:
                out.append(f'<a class="cite" href="#ref-{n}">[{n}]</a>')
        return self.stash(''.join(out))

    def __call__(self, text, cite=True):
        text = text.replace('\x00', '')
        codes = []
        def code(m): codes.append(m.group(2)); return f'\x01{len(codes) - 1}\x01'
        text = re.sub(r'(`+)(.+?)\1', code, text)  # code spans: content kept verbatim (escaped below)
        t = html.escape(text, quote=True)
        t = re.sub(r'\x01(\d+)\x01', lambda m: self.stash(f'<code>{html.escape(codes[int(m.group(1))].strip(), quote=True)}</code>'), t)
        t = re.sub(r'!\[([^\]]*)\]\((?:[^()\s]|\([^()\s]*\))*(?:\s+&quot;[^)]*&quot;)?\)', lambda m: m.group(1), t)  # image: alt text only, never fetched
        t = re.sub(r'\[([^\]\n]+)\]\(((?:[^()\s]|\([^()\s]*\))+)(?:\s+&quot;[^)]*&quot;)?\)', lambda m: self.link(m.group(2), m.group(1)), t)
        t = re.sub(r'&lt;((?:https?://|mailto:)[^\s&]+)&gt;', lambda m: self.link(m.group(1), m.group(1)), t)
        def ident(m):
            v = m.group(2).rstrip(TRAIL); rest = m.group(2)[len(v):]
            return self.link(IDLINK[m.group(1).lower()].format(html.unescape(v)), f'{m.group(1)}:{v}') + rest
        t = ID_RE.sub(ident, t)
        def url(m):
            u = m.group(0); v = u.rstrip(TRAIL); return self.link(v, v) + u[len(v):]
        t = URL_RE.sub(url, t)
        if cite: t = CITE_RE.sub(self.cite, t)
        t = re.sub(r'\*\*(?=\S)(.+?)(?<=\S)\*\*', r'<strong>\1</strong>', t)
        t = re.sub(r'(?<![\w*])__(?=\S)(.+?)(?<=\S)__(?![\w*])', r'<strong>\1</strong>', t)
        t = re.sub(r'(?<![\w*])\*(?=[^\s*])([^*\n]+?)(?<=[^\s*])\*(?![\w*])', r'<em>\1</em>', t)
        t = re.sub(r'(?<![\w_])_(?=[^\s_])([^_\n]+?)(?<=[^\s_])_(?![\w_])', r'<em>\1</em>', t)
        while '\x00' in t: t = re.sub(r'\x00(\d+)\x00', lambda m: self.store[int(m.group(1))], t)
        return t


# ---------- blocks ----------
def slug(s, used):
    b = f'finding-{m.group(1)}' if (m := FINDING_SLUG.match(s.strip())) else re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')[:60] or 'section'
    s, i = b, 2
    while s in used: s, i = f'{b}-{i}', i + 1
    used.add(s); return s


def cells(row):
    row = row.strip()
    if row.startswith('|'): row = row[1:]
    if row.endswith('|') and not row.endswith('\\|'): row = row[:-1]
    out, cur, tick = [], '', False
    i = 0
    while i < len(row):
        c = row[i]
        if c == '\\' and i + 1 < len(row) and row[i + 1] == '|': cur += '|'; i += 2; continue
        if c == '`': tick = not tick
        if c == '|' and not tick: out.append(cur.strip()); cur = ''
        else: cur += c
        i += 1
    return out + [cur.strip()]


SEP = re.compile(r'^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$')
LIST = re.compile(r'^(\s*)([-*+]|\d{1,3}[.)])\s+(.*)$')
HR = re.compile(r'^\s{0,3}([-*_])(\s*\1){2,}\s*$')
HEAD = re.compile(r'^(#{1,6})\s+(.*?)\s*#*\s*$')


def blocks(lines, inl, ctx):
    """Renders a list of lines into HTML blocks. ctx: {'used': ids, 'toc': [(level, id, html)], 'after_h1': callback, 'bib': placeholder}."""
    out, i, n = [], 0, len(lines)
    while i < n:
        l = lines[i]
        if not l.strip(): i += 1; continue
        if (m := re.match(r'^\s*(```+|~~~+)\s*([\w+-]*)', l)):
            fence, body = m.group(1), []; i += 1
            while i < n and not lines[i].strip().startswith(fence): body.append(lines[i]); i += 1
            i += 1; out.append(f'<pre><code>{html.escape(chr(10).join(body), quote=True)}</code></pre>'); continue
        if (m := HEAD.match(l)):
            lvl, raw = len(m.group(1)), m.group(2); i += 1
            if lvl == 2 and RL.canonical(raw) == 'Bibliography' and ctx.get('bib') is not None:   # bibliography: rendered last (back-links)
                body = []
                while i < n and not re.match(r'^#{1,2}\s', lines[i]): body.append(lines[i]); i += 1
                hid = slug(raw, ctx['used']); ctx['toc'].append((2, hid, inl(raw, cite=False)))
                out.append(f'<h2 id="{hid}" class="pb">{inl(raw, cite=False)}</h2>'); out.append(ctx['bib']); ctx['bib_lines'] = body; continue
            if lvl == 1 and not ctx.get('h1_done'):
                ctx['h1_done'] = True; out.append(f'<h1>{inl(raw, cite=False)}</h1>'); out.append(ctx['after_h1']); continue
            hid = slug(raw, ctx['used']); cls = ' class="pb"' if lvl == 2 and RL.canonical(raw) in PAGE_BREAK else ''
            if lvl in (2, 3): ctx['toc'].append((lvl, hid, inl(raw, cite=False)))
            out.append(f'<h{lvl} id="{hid}"{cls}>{inl(raw)}</h{lvl}>'); continue
        if HR.match(l): out.append('<hr>'); i += 1; continue
        if l.lstrip().startswith('>'):
            q = []
            while i < n and lines[i].strip() and lines[i].lstrip().startswith('>'): q.append(re.sub(r'^\s*>\s?', '', lines[i])); i += 1
            out.append('<blockquote>' + blocks(q, inl, {**ctx, 'bib': None}) + '</blockquote>'); continue
        if '|' in l and i + 1 < n and SEP.match(lines[i + 1]) and '|' in lines[i + 1]:
            head, al = cells(l), cells(lines[i + 1]); i += 2
            align = ['center' if a.startswith(':') and a.endswith(':') else 'right' if a.endswith(':') else 'left' if a.startswith(':') else '' for a in al]
            st = lambda k: f' style="text-align:{align[k]}"' if k < len(align) and align[k] else ''
            rows = []
            while i < n and lines[i].strip() and '|' in lines[i]: rows.append(cells(lines[i])); i += 1
            th = ''.join(f'<th{st(k)}>{inl(c)}</th>' for k, c in enumerate(head))
            tb = ''.join('<tr>' + ''.join(f'<td{st(k)}>{inl(c)}</td>' for k, c in enumerate(r[:len(head)] + [''] * (len(head) - len(r)))) + '</tr>' for r in rows)
            out.append(f'<div class="tw"><table><thead><tr>{th}</tr></thead><tbody>{tb}</tbody></table></div>'); continue
        if (m := LIST.match(l)):
            ind, ordered = len(m.group(1)), m.group(2)[0].isdigit()
            start = int(re.match(r'\d+', m.group(2)).group(0)) if ordered else 1
            items = []
            while i < n:
                m2 = LIST.match(lines[i])
                if m2 and len(m2.group(1)) == ind and m2.group(2)[0].isdigit() == ordered:
                    items.append([m2.group(3)]); i += 1; continue
                if items and lines[i].strip() and (len(lines[i]) - len(lines[i].lstrip()) > ind): items[-1].append(lines[i]); i += 1; continue
                if items and not lines[i].strip() and i + 1 < n and (LIST.match(lines[i + 1]) and len(LIST.match(lines[i + 1]).group(1)) >= ind
                                                                      or len(lines[i + 1]) - len(lines[i + 1].lstrip()) > ind):
                    items[-1].append(''); i += 1; continue
                break
            lis = []
            for it in items:
                sub = [it[0]] + [re.sub(r'^\s{1,%d}' % (ind + 4), '', x) for x in it[1:]]
                if len(sub) == 1 or not any(LIST.match(x) or not x.strip() for x in sub[1:]): lis.append(f'<li>{inl(" ".join(x.strip() for x in sub))}</li>')
                else:
                    k = next(j for j, x in enumerate(sub) if j and (LIST.match(x) or not x.strip()))
                    lis.append(f'<li>{inl(" ".join(x.strip() for x in sub[:k]))}{blocks(sub[k:], inl, {**ctx, "bib": None})}</li>')
            tag = 'ol' if ordered else 'ul'; s = f' start="{start}"' if ordered and start != 1 else ''
            out.append(f'<{tag}{s}>' + ''.join(lis) + f'</{tag}>'); continue
        p = []
        while i < n and lines[i].strip() and not (HEAD.match(lines[i]) or LIST.match(lines[i]) or lines[i].lstrip().startswith(('>', '```', '~~~'))
                                                  or HR.match(lines[i]) or ('|' in lines[i] and i + 1 < n and SEP.match(lines[i + 1]))):
            p.append(lines[i].strip()); i += 1
        if not p: p, i = [l.strip()], i + 1
        cls = ' class="pre"' if not ctx.get('h1_done') else ''
        out.append(f'<p{cls}>{inl(" ".join(p))}</p>')
    return '\n'.join(out)


def _passage_html(p):
    t, out, i = p['text'], [], 0
    for a, b in sorted(p.get('marks') or []):
        if a < i: continue
        out += [html.escape(t[i:a], quote=True), '<mark>', html.escape(t[a:b], quote=True), '</mark>']; i = b
    out.append(html.escape(t[i:], quote=True))
    return '<blockquote>' + ''.join(out) + (' [&#8230;]' if p.get('truncated') else '') + '</blockquote>'


def passages_html(claims):
    """Block of the cited passages of one reference (tools/passages.py output): every piece escaped, the passage is source text, never markup."""
    out = []
    for c in claims:
        st = str(c.get('status') or ''); cls = '' if st == 'FOUND' else ' d' if st == 'DISTORTED' else ' n'
        o = c.get('origin') or {}
        org = ', '.join(x for x in (o.get('id'), o.get('kind'), ' '.join(x for x in (o.get('version'), f"({o['version_date']})" if o.get('version_date') else '') if x)) if x)
        out.append(f'<div class="c"><span class="id">{html.escape(str(c.get("id")))}</span><span class="st{cls}">{html.escape(st)}</span>'
                   f'{html.escape(" ".join(str(c.get("claim") or "").split()), quote=True)}</div>')
        if c.get('passages'):
            out += [_passage_html(p) for p in c['passages']]
            out.append(f'<div class="o">Source text read by the verifier: {html.escape(org, quote=True)}</div>')
        else:
            out.append(f'<div class="none">{html.escape(str(c.get("reason") or "no verified passage"), quote=True)}'
                       + (f' ({html.escape(org, quote=True)})' if org else '') + '.</div>')
    return '<div class="cp">' + ''.join(out) + '</div>' if out else ''


def bibliography(lines, inl, cited=None):
    entries, cur = [], None
    for l in lines:
        if (m := BIB_LINE.match(l)): cur = [int(m.group(1)), m.group(2).strip()]; entries.append(cur)
        elif l.strip() and cur: cur[1] += ' ' + l.strip()
        elif l.strip(): entries.append([None, l.strip()])
    out = []
    for num, text in entries:
        if num is None: out.append(f'<p>{inl(text)}</p>'); continue
        back = ''.join(f' <a href="#{c}" title="back to citation">&#8617;{chr(97 + k) if k < 26 else k + 1}</a>' for k, c in enumerate(inl.cites.get(num, [])))
        out.append(f'<p id="ref-{num}"><span class="n">[{num}]</span>{inl(text, cite=False)}'
                   + (f'<span class="back">{back}</span>' if back else '') + '</p>')
        if cited: out.append(passages_html(cited.get(num, [])))
    if cited and cited.get(None):
        out.append('<p>Claims whose source is not in this bibliography:</p>' + passages_html(cited[None]))
    if cited:
        out.insert(0, '<p class="pre">Under each reference: the claims checked against it, each with the passage of the source that supports '
                      'it (verified fragment highlighted), copied by code from the text the verifier read, never written by a model.</p>')
    return '<div class="bib">\n' + '\n'.join(out) + '\n</div>'


def render(md, meta=(), title_fallback='Report', passages=None, extra=()):
    """REPORT.md text + [(label, value)] (+ tools/passages.py build() output) (+ optional appendices [(id, title, html)], placed after the
    report and listed in the contents) -> complete HTML page (str)."""
    md = md.replace('\r\n', '\n').replace('\r', '\n').replace('\x00', '')
    lines = md.split('\n')
    refs, inbib = set(), False
    for l in lines:
        if re.match(r'^##\s', l): inbib = RL.canonical(l.strip()[2:].strip()) == 'Bibliography'
        elif inbib and (m := BIB_LINE.match(l)): refs.add(int(m.group(1)))
    inl = Inline(refs)
    h1 = next((HEAD.match(l).group(2) for l in lines if HEAD.match(l) and len(HEAD.match(l).group(1)) == 1), None)
    ctx = {'used': {'contents'}, 'toc': [], 'after_h1': '\x02HEADER\x02', 'bib': '\x02BIB\x02'}
    body = blocks(lines, inl, ctx)
    cited = {}
    for c in (passages or {}).get('claims') or []: cited.setdefault(c.get('ref'), []).append(c)
    bib = bibliography(ctx.get('bib_lines', []), inl, cited)
    for xid, xtitle, xhtml in extra:
        hid = slug(xid, ctx['used']); ctx['toc'].append((2, hid, html.escape(xtitle)))
        body += f'\n<h2 id="{hid}" class="pb">{html.escape(xtitle)}</h2>\n{xhtml}'
    dl = ''.join(f'<dt>{html.escape(k)}</dt><dd>{html.escape(str(v))}</dd>' for k, v in meta)
    toc, open3 = [], False
    for lvl, hid, label in ctx['toc']:
        if lvl == 2:
            if open3: toc.append('</ol>'); open3 = False
            if toc: toc.append('</li>')
            toc.append(f'<li><a href="#{hid}">{label}</a>')
        else:
            if not open3: toc.append('<ol>'); open3 = True
            toc.append(f'<li><a href="#{hid}">{label}</a></li>')
    if open3: toc.append('</ol>')
    if toc: toc.append('</li>')
    head = (f'<div class="meta"><dl>{dl}</dl></div>' if dl else '') + (f'<nav id="contents"><div class="t">Contents</div><ol>{"".join(toc)}</ol></nav>' if toc else '')
    body = body.replace('\x02BIB\x02', bib)
    body = body.replace('\x02HEADER\x02', head) if '\x02HEADER\x02' in body else head + body
    title = html.escape(re.sub(r'[`*_]', '', h1 or title_fallback).strip(), quote=True)
    gen = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    lang = RL.report_language(md) if any(RL.canonical(t) for t, _ in RL.raw_sections(md)) else RL.DEFAULT
    return (f'<!DOCTYPE html>\n<html lang="{lang}">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src data:">\n'
            f'<meta name="generator" content="VanishingPoint export_report.py">\n<title>{title}</title>\n<style>{CSS}</style>\n</head>\n<body>\n<main>\n{body}\n</main>\n'
            f'<footer>Exported from REPORT.md by VanishingPoint on {gen}. The citations [n] link to the bibliography.</footer>\n</body>\n</html>\n')


# ---------- header ----------
def _json(p):
    try: return json.loads(p.read_text(encoding='utf-8'))
    except Exception: return None


def _join(v):
    return ', '.join(str(x) for x in v) if isinstance(v, list) else str(v) if v not in (None, '') else ''


def meta(folder):
    """Header fields that the run's files give; absent files or fields are simply left out."""
    d = pathlib.Path(folder)
    card, run, res, ver = (_json(d / f) for f in ('card.json', 'run.json', 'result.json', 'verdicts.json'))
    card, run, res = (x if isinstance(x, dict) else {} for x in (card, run, res))
    try: scope = (d / 'scope.md').read_text(encoding='utf-8')[:3000]
    except Exception: scope = ''
    try: report = (d / 'REPORT.md').read_text(encoding='utf-8')
    except Exception: report = ''
    sc = lambda rx: (m.group(1).strip().rstrip('.') if (m := re.search(rx, scope, re.M)) else '')
    out = []
    if card.get('question'): out.append(('Question', card['question']))
    if (t := _join(run.get('T')) or _join(card.get('T')) or sc(r'\bT\s*=\s*(\d{4}-\d{2}-\d{2}[\dT:Z+-]*)')): out.append(('Date T', t))
    if (p := _join(run.get('plugins') or run.get('plugin') or card.get('plugins')) or sc(r'\bPlugins?:\s*([^.\n]+)')): out.append(('Plugin(s)', p))
    mode = _join(run.get('mode')) or sc(r'\bMode:\s*([\w-]+)')
    if not mode and (m := re.search(r'\bMode\s?:\s*(standard|audit)\b', RL.section(report, 'Methodology Appendix'))): mode = m.group(1)
    if mode: out.append(('Mode', mode))
    if isinstance(ver, dict) and isinstance(ver.get('claims'), list) and ver['claims']:
        counts = {}
        for c in ver['claims']:
            if isinstance(c, dict): counts[str(c.get('status'))] = counts.get(str(c.get('status')), 0) + 1
        order = ['FOUND', 'DISTORTED', 'ABSENT', 'INVALID', 'SOURCE-UNAVAILABLE', 'UNVERIFIED']
        ks = [k for k in order if k in counts] + sorted(k for k in counts if k not in order)
        out.append(('Verification', f'{sum(counts.values())} claims checked: ' + ', '.join(f'{k} {counts[k]}' for k in ks)))
    elif isinstance(res.get('verification'), dict) and res['verification'].get('rule'): out.append(('Verification', res['verification']['rule']))
    calls = run.get('calls', res.get('calls_used'))
    if isinstance(calls, int): out.append(('Gateway calls', calls))
    if (r := _join(run.get('run')) or _join(card.get('card_id'))): out.append(('Run', r))
    return out


def cited_passages(folder):
    """tools/passages.py build() for the run, or None (no verdicts.json, or any failure: the report is exported without the blocks)."""
    try:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent)); import passages
        return passages.build(folder)
    except Exception:
        return None


# ---------- optional appendices ----------
def extras(folder, prisma=False, followups=False):
    """[(id, title, html)] of the optional appendices asked for; a tool that fails leaves its appendix out with one escaped line."""
    out = []
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    if prisma:
        try:
            import prisma as _pr
            data = _pr.build(folder)
            out.append(('prisma', 'PRISMA 2020 flow diagram', f'<div class="tw">{_pr.svg(data)}</div><p class="pre">{html.escape(_pr.DEFINITIONS)}</p>'))
        except Exception as e:
            out.append(('prisma', 'PRISMA 2020 flow diagram', f'<p class="pre">Not produced: {html.escape(type(e).__name__)}.</p>'))
    if followups:
        try:
            import followups as _fu
            data = _fu.build(folder)
            items = ''.join(f'<li>{html.escape(q["text"])} <span class="pre">({html.escape(q["family"])}; from {html.escape(q["from"])})</span></li>' for q in data['questions'])
            note = ('<p class="pre">Derived mechanically from this run by fixed templates (tools/followups.py); no model wrote them.'
                    + (f' Only {len(data["questions"])} question(s) derivable; none invented to reach {data["min"]}.' if data['short'] else '') + '</p>')
            out.append(('followups', 'Follow-up questions', note + (f'<ol>{items}</ol>' if items else '<p>No follow-up question is derivable from this run.</p>')))
        except Exception as e:
            out.append(('followups', 'Follow-up questions', f'<p class="pre">Not produced: {html.escape(type(e).__name__)}.</p>'))
    return out


# ---------- PDF ----------
def _ok(pdf):
    try: return pdf.stat().st_size > 0 and pdf.read_bytes()[:4] == b'%PDF'
    except OSError: return False


def _run(cmd, **kw):
    try: p = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT, **kw); return p.returncode, p.stderr.decode('utf-8', 'replace')
    except (OSError, subprocess.SubprocessError) as e: return -1, str(e)


def _in_container():
    if os.path.exists('/.dockerenv') or os.path.exists('/run/.containerenv'): return True
    try: return any(k in pathlib.Path('/proc/1/cgroup').read_text() for k in ('docker', 'kubepods', 'containerd', 'lxc'))
    except OSError: return False


def _weasy_module(src, pdf):
    try: wp = importlib.import_module('weasyprint')
    except Exception: return None   # absent, or present without its system libraries
    def refuse(url, *a, **k): raise ValueError('no external resource')   # never any fetch
    try:
        wp.HTML(string=src.read_text(encoding='utf-8'), base_url=str(src.parent), url_fetcher=refuse).write_pdf(str(pdf)); return _ok(pdf)
    except Exception: return False


def _weasy_cmd(exe, src, pdf):
    return _run([exe, '--quiet', str(src), str(pdf)])[0] == 0 and _ok(pdf)


SANDBOX_FAIL = re.compile(r'namespace|sandbox|zygote', re.I)


def _chrome(exe, src, pdf):
    with tempfile.TemporaryDirectory(prefix='vp-chrome-') as prof:
        base = [exe, '--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--disable-extensions', '--disable-sync',
                '--disable-background-networking', '--disable-component-update', '--disable-dev-shm-usage', '--host-resolver-rules=MAP * ~NOTFOUND',
                f'--user-data-dir={prof}', '--no-pdf-header-footer', '--print-to-pdf-no-header', f'--print-to-pdf={pdf}', src.resolve().as_uri()]
        env = {**os.environ, 'HOME': prof}
        rc, err = _run(base, env=env)
        if rc == 0 and _ok(pdf): return True
        # sandbox first; --no-sandbox only inside a container, as root or when the sandbox itself failed to start (no user namespaces)
        if _in_container() and ((hasattr(os, 'geteuid') and os.geteuid() == 0) or SANDBOX_FAIL.search(err)):
            return _run(base[:1] + ['--no-sandbox'] + base[1:], env=env)[0] == 0 and _ok(pdf)
    return False


def _wkhtml(exe, src, pdf):
    return _run([exe, '--quiet', '--disable-javascript', '--page-size', 'A4', '--encoding', 'utf-8', str(src), str(pdf)])[0] == 0 and _ok(pdf)


def _pandoc(exe, engine, src, pdf):
    return _run([exe, '-f', 'html', str(src), '-o', str(pdf), f'--pdf-engine={engine}'])[0] == 0 and _ok(pdf)


CHROMES = ('chromium', 'chromium-browser', 'google-chrome', 'google-chrome-stable', 'chrome')
PANDOC_ENGINES = ('weasyprint', 'wkhtmltopdf', 'prince', 'typst', 'xelatex', 'lualatex', 'pdflatex')  # local engines only (tectonic, pagedjs-cli fetch from the network)


def _has_module(name):
    if name in sys.modules: return sys.modules[name] is not None   # None = blocked (tests)
    try: return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError): return False


def converters():
    """[(name, callable(src, pdf) -> True/False/None)] in the order of trial; only what is present (nothing is installed)."""
    which = lambda x: shutil.which(x, path=os.environ.get('PATH', ''))
    out = []
    if _has_module('weasyprint'): out.append(('weasyprint (module)', _weasy_module))
    if (e := which('weasyprint')): out.append(('weasyprint', lambda s, p, e=e: _weasy_cmd(e, s, p)))
    for c in CHROMES:
        if (e := which(c)): out.append((c, lambda s, p, e=e: _chrome(e, s, p))); break
    if (e := which('wkhtmltopdf')): out.append(('wkhtmltopdf', lambda s, p, e=e: _wkhtml(e, s, p)))
    if (e := which('pandoc')):
        for g in PANDOC_ENGINES:
            if which(g): out.append((f'pandoc --pdf-engine={g}', lambda s, p, e=e, g=g: _pandoc(e, g, s, p))); break
    return out


def to_pdf(src, pdf):
    """Tries each converter in order; returns (name or None, [names tried])."""
    tried = []
    for name, f in converters():
        tried.append(name)
        try: pdf.unlink()
        except OSError: pass
        if f(src, pdf): return name, tried
    try:
        if not _ok(pdf): pdf.unlink()
    except OSError: pass
    return None, tried


def can_open():
    """The viewer command of a desktop session: `open` on macOS, `xdg-open` with a display on Linux, `start` on Windows; else None
    (a server or a container has no screen: nothing is opened)."""
    if sys.platform == 'darwin': return ['open'] if shutil.which('open') else None
    if os.name == 'nt': return ['cmd', '/c', 'start', '']
    if (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')) and shutil.which('xdg-open'): return ['xdg-open']
    return None


def open_file(path):
    """Opens the file with the desktop viewer when there is one; returns True if a viewer was launched (never waits for it)."""
    cmd = can_open()
    if not cmd: return False
    try: subprocess.Popen(cmd + [str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=os.name != 'nt'); return True
    except OSError: return False


def main(argv=None):
    ap = argparse.ArgumentParser(description='REPORT.md -> REPORT.html (always) and REPORT.pdf (--pdf), offline.')
    ap.add_argument('run_dir'); ap.add_argument('--pdf', action='store_true'); ap.add_argument('--out')
    ap.add_argument('--open', action='store_true', help='open the PDF (else the HTML) with the desktop viewer, if the machine has a screen')
    ap.add_argument('--prisma', action='store_true', help='optional: append the PRISMA 2020 flow diagram (tools/prisma.py)')
    ap.add_argument('--followups', action='store_true', help='optional: append the follow-up questions (tools/followups.py)')
    a = ap.parse_args(argv)
    d = pathlib.Path(a.run_dir); src = d / 'REPORT.md'
    if not src.is_file(): print(f'no REPORT.md in {d}', file=sys.stderr); return 2
    out = pathlib.Path(a.out) if a.out else d; out.mkdir(parents=True, exist_ok=True)
    page = out / 'REPORT.html'
    page.write_text(render(src.read_text(encoding='utf-8', errors='replace'), meta(d), passages=cited_passages(d), extra=extras(d, a.prisma, a.followups)), encoding='utf-8')
    print(f'{page.resolve()}')
    if a.pdf:
        pdf = out / 'REPORT.pdf'
        name, tried = to_pdf(page, pdf)
        if name: print(f'{pdf.resolve()} ({name})')
        elif not tried: print('PDF: no converter found (WeasyPrint, Chromium/Chrome, wkhtmltopdf, pandoc); REPORT.html prints to PDF from any browser.')
        else: print(f'PDF: conversion failed ({", ".join(tried)}); REPORT.html prints to PDF from any browser.')
    if a.open:
        shown = out / 'REPORT.pdf' if a.pdf and (out / 'REPORT.pdf').is_file() else page
        if open_file(shown): print(f'opened: {shown.name}')   # no screen: silent
    return 0


if __name__ == '__main__':
    sys.exit(main())
