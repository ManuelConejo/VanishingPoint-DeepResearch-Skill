#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Polite retrieval of the open-access full text of a source.

Usage:
  python3 -I fetch_fulltext.py --arxiv 2503.01234 --out DIR
  python3 -I fetch_fulltext.py --doi 10.1038/xxx --out DIR
  python3 -I fetch_fulltext.py --pmcid PMC123 --out DIR

Cascade: arXiv (LaTeX source -> HTML -> PDF); Europe PMC (full-text XML);
Unpaywall (locates a free copy -> arXiv / PMC / PDF / HTML; needs VP_CONTACT).
Outputs in DIR: source.txt (readable text), possibly source.pdf
(to be read by the agent when no text can be extracted), meta.json.

Politeness: User-Agent with a contact (env VP_CONTACT, no default), 1 request / 3 s to arXiv,
1 request / s elsewhere, local cache (nothing is downloaded again when source.txt exists).
PDF text extraction uses pypdf when it is installed (optional); otherwise source.pdf is kept for the agent.
"""
import argparse, gzip, html, io, json, os, re, sys, tarfile, time
import urllib.parse, urllib.request, urllib.error

CONTACT = os.environ.get("VP_CONTACT", "").strip()
UA = "VanishingPoint-verifier/0.1 (academic research" + (f"; contact:{CONTACT}" if CONTACT else "") + ")"
DELAYS = {"arxiv.org": 3.0, "export.arxiv.org": 3.0}
DEFAULT_DELAY = 1.0
_last = {}
MAX_BYTES = 60 * 1024 * 1024


def get(url, accept=None):
    host = urllib.parse.urlparse(url).hostname or ""
    key = "arxiv.org" if host.endswith("arxiv.org") else host
    # rate also respected across processes: a timestamp file shared per remote host
    stamp = os.path.join(os.path.expanduser("~/.cache/vp-verifier"), key)
    os.makedirs(os.path.dirname(stamp), exist_ok=True)
    try:
        last = max(_last.get(key, 0), os.path.getmtime(stamp))
    except OSError:
        last = _last.get(key, 0)
    wait = DELAYS.get(key, DEFAULT_DELAY) - (time.time() - last)
    if wait > 0:
        time.sleep(wait)
    open(stamp, "a").close(); os.utime(stamp)
    req = urllib.request.Request(url, headers={"User-Agent": UA, **({"Accept": accept} if accept else {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read(MAX_BYTES + 1)
            return r.status, r.headers.get("Content-Type", ""), data, r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, "", b"", url
    except Exception as e:  # network
        return 0, str(e), b"", url
    finally:
        _last[key] = time.time()


def html_to_text(b):
    t = b.decode("utf-8", "replace")
    t = re.sub(r"(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", t)
    t = re.sub(r"(?i)<math[^>]*alttext=\"([^\"]*)\"[^>]*>.*?</math>", r" \1 ", t, flags=re.S)
    t = re.sub(r"(?i)</(p|div|h\d|li|tr|caption|figcaption|section|table)>", "\n", t)
    t = re.sub(r"(?i)<(br|/td|/th)[^>]*>", " | ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def xml_to_text(b):
    t = b.decode("utf-8", "replace")
    t = re.sub(r"(?i)</(p|title|caption|tr|sec|table-wrap|fig|label)>", "\n", t)
    t = re.sub(r"(?i)</(td|th)>", " | ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def latex_from_eprint(data):
    """Concatenates the .tex files of an arXiv e-print (tar.gz or plain .gz), main file first."""
    try:
        tf = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
        texs = {}
        for m in tf.getmembers():
            if m.isfile() and m.name.endswith((".tex", ".bbl")) and m.size < 5_000_000:
                texs[m.name] = tf.extractfile(m).read().decode("utf-8", "replace")
        if not texs:
            return None
        main = [n for n, c in texs.items() if "\\documentclass" in c]
        order = main + sorted(n for n in texs if n not in main)
        return "\n\n".join(f"%%%%% FILE {n} %%%%%\n{texs[n]}" for n in order)
    except tarfile.TarError:
        try:
            t = gzip.decompress(data).decode("utf-8", "replace")
        except OSError:
            t = data.decode("utf-8", "replace")
        return t if "\\begin{document}" in t or "\\section" in t else None


PDF_ONLY = False  # --pdf-only: simulates a source available only as PDF


def via_arxiv(aid, out):
    aid = re.sub(r"^(arxiv:)", "", aid, flags=re.I)
    if PDF_ONLY:
        s, ct, d, _ = get(f"https://arxiv.org/pdf/{aid}")
        return write_pdf(out, d, "arxiv-pdf", f"https://arxiv.org/pdf/{aid}") if s == 200 and d.startswith(b"%PDF") else None
    s, ct, d, _ = get(f"https://arxiv.org/e-print/{aid}")
    if s == 200 and d and not d.startswith(b"%PDF"):
        tex = latex_from_eprint(d)
        if tex and len(tex) > 2000:
            return write(out, tex, "arxiv-latex", f"https://arxiv.org/e-print/{aid}")
    s, ct, d, _ = get(f"https://arxiv.org/html/{aid}")
    if s == 200 and d:
        t = html_to_text(d)
        if len(t) > 5000:
            return write(out, t, "arxiv-html", f"https://arxiv.org/html/{aid}")
    s, ct, d, _ = get(f"https://arxiv.org/pdf/{aid}")
    if s == 200 and d.startswith(b"%PDF"):
        return write_pdf(out, d, "arxiv-pdf", f"https://arxiv.org/pdf/{aid}")
    return None


def via_epmc(pmcid, out):
    s, ct, d, _ = get(f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML")
    if s == 200 and d:
        t = xml_to_text(d)
        if len(t) > 3000:
            return write(out, t, "europepmc-xml", f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML")
    return None


def pmcid_from_doi(doi):
    q = urllib.parse.quote(f'DOI:"{doi}"')
    s, ct, d, _ = get(f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?query={q}&format=json&resultType=lite")
    if s != 200:
        return None
    for r in json.loads(d).get("resultList", {}).get("result", []):
        if r.get("pmcid") and r.get("isOpenAccess") == "Y":
            return r["pmcid"]
        if r.get("pmcid"):
            return r["pmcid"]
    return None


def via_rxiv(doi, out):
    """bioRxiv / medRxiv preprints: PDF of the latest version (official API)."""
    for server in ("medrxiv", "biorxiv"):
        s, ct, d, _ = get(f"https://api.{server}.org/details/{server}/{doi}")
        if s != 200:
            continue
        coll = json.loads(d).get("collection") or []
        if not coll:
            continue
        v = coll[-1].get("version", "1")
        url = f"https://www.{server}.org/content/{doi}v{v}.full.pdf"
        s, ct, d, final = get(url)
        if s == 200 and d.startswith(b"%PDF"):
            return write_pdf(out, d, f"{server}-pdf", final)
    return None


def via_doi(doi, out):
    m = re.match(r"10\.48550/arxiv\.(.+)", doi, re.I)
    if m:
        return via_arxiv(m.group(1), out)
    if re.match(r"10\.(1101|64898)/", doi):
        r = via_rxiv(doi, out)
        if r:
            return r
    pmcid = None if PDF_ONLY else pmcid_from_doi(doi)
    if pmcid:
        r = via_epmc(pmcid, out)
        if r:
            return r
    if not CONTACT:  # Unpaywall requires a contact address: set VP_CONTACT to enable this step
        return None
    s, ct, d, _ = get(f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email={urllib.parse.quote(CONTACT)}")
    if s != 200:
        return None
    u = json.loads(d)
    locs = [u.get("best_oa_location")] + (u.get("oa_locations") or [])
    for loc in [l for l in locs if l]:
        for url in (loc.get("url_for_landing_page"), loc.get("url_for_pdf"), loc.get("url")):
            if not url:
                continue
            a = re.search(r"arxiv\.org/(?:abs|pdf)/([^/?#v]+(?:v\d+)?)", url)
            if a:
                r = via_arxiv(a.group(1), out)
                if r:
                    return r
            p = re.search(r"(PMC\d+)", url)
            if p:
                r = via_epmc(p.group(1), out)
                if r:
                    return r
    for loc in [l for l in locs if l]:
        for url in (loc.get("url_for_pdf"), loc.get("url_for_landing_page")):
            if not url:
                continue
            s, ct, d, final = get(url)
            if s == 200 and d.startswith(b"%PDF"):
                return write_pdf(out, d, "unpaywall-pdf", final)
            if s == 200 and "html" in ct:
                t = html_to_text(d)
                if len(t) > 15000:  # publisher page with the full text, not a mere abstract
                    return write(out, t, "unpaywall-html", final)
    return None


def write(out, text, method, url):
    open(os.path.join(out, "source.txt"), "w").write(text)
    return {"status": "OK", "method": method, "url": url, "chars": len(text)}


def pdf_to_text(path):
    """Text of a PDF via pypdf (optional dependency: installed package, or a _vendor directory next to this file)."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_vendor"))
    try:
        import pypdf
        reader = pypdf.PdfReader(path)
        pages = [f"=== PAGE {i + 1} ===\n" + (p.extract_text() or "") for i, p in enumerate(reader.pages)]
        return "\n\n".join(pages)
    except Exception:  # pypdf missing, encrypted, corrupted or scanned PDF...
        return ""


def write_pdf(out, data, method, url):
    path = os.path.join(out, "source.pdf")
    open(path, "wb").write(data)
    text = pdf_to_text(path)
    if len(text) > 3000:
        open(os.path.join(out, "source.txt"), "w").write(text)
        return {"status": "OK", "method": method + "-text", "url": url, "chars": len(text),
                "note": "text extracted from the PDF (pypdf): tables and formulas possibly out of order"}
    return {"status": "OK-PDF", "method": method, "url": url, "bytes": len(data),
            "note": "no extractable text (scan, or pypdf not installed): the agent reads source.pdf directly"}


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--arxiv"); g.add_argument("--doi"); g.add_argument("--pmcid")
    ap.add_argument("--out", required=True)
    ap.add_argument("--pdf-only", action="store_true", help="use only the PDF (sources available as PDF only)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    mp = os.path.join(a.out, "meta.json")
    if os.path.exists(mp) and json.load(open(mp)).get("status", "").startswith("OK"):
        print(open(mp).read()); return
    t0 = time.time()
    global PDF_ONLY
    PDF_ONLY = a.pdf_only
    r = (via_arxiv(a.arxiv, a.out) if a.arxiv else via_epmc(a.pmcid, a.out) if a.pmcid else via_doi(a.doi, a.out))
    r = r or {"status": "SOURCE-UNAVAILABLE", "note": "no usable free copy found"}
    r.update({"id": a.arxiv or a.doi or a.pmcid, "seconds": round(time.time() - t0, 1)})
    json.dump(r, open(mp, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    main()
