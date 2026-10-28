#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Polite retrieval of the open-access full text of a source.

Usage:
  python3 -I fetch_fulltext.py --arxiv 2503.01234 --T 2025-06-01 --out DIR
  python3 -I fetch_fulltext.py --doi 10.1038/xxx --T 2025-06-01 --out DIR
  python3 -I fetch_fulltext.py --pmcid PMC123 --T 2025-06-01 --out DIR

Date rule (T = date of the question, as in tools/gateway.py): nothing dated on or after T is read. No --T -> no full text (REFUSED).
arXiv: the last version submitted before T (dates from OAI-PMH arXivRaw), then LaTeX source -> HTML -> PDF of that version only.
bioRxiv / medRxiv: the last version posted before T (api.biorxiv.org); its full text is only on www.biorxiv.org / www.medrxiv.org,
never called (robots.txt disallows AI crawlers): SOURCE-UNAVAILABLE with the version, the abstract comes from the gateway.
Europe PMC full-text XML: only when the article was first published before T; Unpaywall (needs VP_CONTACT): arXiv and PMC copies
under the rules above, publisher copies only when published before T. Europe PMC and publisher texts are flagged (`warning`): the
open-access text may be a later corrected version. No version before T -> REFUSED with a reason, nothing downloaded.
Outputs in DIR: source.txt (readable text), possibly source.pdf
(to be read by the agent when no text can be extracted), meta.json (status, reason, version pinned, T).

Politeness: User-Agent with a contact (env VP_CONTACT, no default), 1 request / 3 s to arXiv,
1 request / s elsewhere, local cache (nothing is downloaded again for the same T; a copy fetched for another T is deleted).
PDF text extraction uses pypdf when it is installed (optional); otherwise source.pdf is kept for the agent.
"""
import argparse, datetime as dt, email.utils, gzip, html, io, json, os, re, sys, tarfile, time
import xml.etree.ElementTree as ET
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
T = None          # date of the question (--T): nothing dated on or after T is read; no T -> no full text at all
LATER = ("open-access full text = the version deposited now: it may carry corrections or updates made on/after T "
         "(not datable); a passage found only in the full text is to be weighed against the record and abstract")


def before_T(d):
    """A date (date, or ISO string, partial allowed: upper bound of the period) strictly before T; unknown -> False."""
    if isinstance(d, dt.date): return d < T
    m = re.match(r"(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", str(d or ""))
    if not m: return False
    y, mo, da = int(m.group(1)), int(m.group(2) or 12), m.group(3)
    up = dt.date(y, mo, int(da)) if da else (dt.date(y + mo // 12, mo % 12 + 1, 1) - dt.timedelta(days=1))
    return up < T


def refuse(status, reason, **kw):
    return dict(status=status, reason=reason, **kw)


def ok(r):
    return bool(r) and str(r.get("status", "")).startswith("OK")


def arxiv_versions(base):
    """[(n, submission date UTC)] from arXiv OAI-PMH (arXivRaw, documented API); [] unknown id; None host unreachable or unreadable."""
    s, ct, d, _ = get("https://oaipmh.arxiv.org/oai?" + urllib.parse.urlencode(
        {"verb": "GetRecord", "identifier": "oai:arXiv.org:" + base, "metadataPrefix": "arXivRaw"}))
    if s != 200 or not d:
        return None
    try:
        root = ET.fromstring(d)
    except ET.ParseError:
        return None
    if any(e.get("code") == "idDoesNotExist" for e in root.iter("{http://www.openarchives.org/OAI/2.0/}error")):
        return []
    out = []
    for v in root.iter("{http://arxiv.org/OAI/arXivRaw/}version"):
        try:
            out.append((int(v.get("version", "v0")[1:]), email.utils.parsedate_to_datetime(v.findtext("{http://arxiv.org/OAI/arXivRaw/}date")).astimezone(dt.timezone.utc).date()))
        except (TypeError, ValueError):
            return None                                   # an undatable version: nothing can be pinned
    return sorted(out)


def via_arxiv(aid, out):
    """The last version submitted before T (arXivRaw dates); an explicit vN is a ceiling. LaTeX -> HTML -> PDF of THAT version only."""
    m = re.fullmatch(r"(.+?)(?:v(\d+))?", re.sub(r"^arxiv:", "", aid.strip(), flags=re.I))
    base, want = m.group(1), m.group(2)
    vs = arxiv_versions(base)
    if vs is None:
        return refuse("SOURCE-UNAVAILABLE", "arXiv version history unreachable (oaipmh.arxiv.org): no version datable, nothing read")
    if not vs:
        return refuse("SOURCE-UNAVAILABLE", f"arXiv {base}: unknown identifier")
    seen = [(n, d) for n, d in vs if before_T(d) and (not want or n <= int(want))]
    if not seen:
        return refuse("REFUSED", f"no arXiv version of {base} submitted before T {T} (v1: {vs[0][1]})")
    n, d = seen[-1]
    vid = f"{base}v{n}"
    pin = {"version": f"v{n}", "version_date": d.isoformat(), "versions_total": len(vs), "later_versions_masked": n < vs[-1][0]}
    r = None
    if PDF_ONLY:
        s, ct, b, _ = get(f"https://arxiv.org/pdf/{vid}")
        r = write_pdf(out, b, "arxiv-pdf", f"https://arxiv.org/pdf/{vid}") if s == 200 and b.startswith(b"%PDF") else None
    else:
        s, ct, b, _ = get(f"https://arxiv.org/e-print/{vid}")
        if s == 200 and b and not b.startswith(b"%PDF"):
            tex = latex_from_eprint(b)
            if tex and len(tex) > 2000:
                r = write(out, tex, "arxiv-latex", f"https://arxiv.org/e-print/{vid}")
        if not r:
            s, ct, b, _ = get(f"https://arxiv.org/html/{vid}")
            t = html_to_text(b) if s == 200 and b else ""
            if len(t) > 5000:
                r = write(out, t, "arxiv-html", f"https://arxiv.org/html/{vid}")
        if not r:
            s, ct, b, _ = get(f"https://arxiv.org/pdf/{vid}")
            if s == 200 and b.startswith(b"%PDF"):
                r = write_pdf(out, b, "arxiv-pdf", f"https://arxiv.org/pdf/{vid}")
    return dict(r, **pin) if r else refuse("SOURCE-UNAVAILABLE", f"arXiv {vid} (last version before T): no LaTeX, HTML nor PDF obtained", **pin)


def epmc_record(query):
    s, ct, d, _ = get("https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode({"query": query, "format": "json", "resultType": "lite"}))
    if s != 200:
        return None
    res = json.loads(d).get("resultList", {}).get("result", [])
    return next((r for r in res if r.get("pmcid") and r.get("isOpenAccess") == "Y"), None) or next((r for r in res if r.get("pmcid")), None)


def via_epmc(pmcid, out, rec=None):
    """Europe PMC full-text XML, only when the article's first publication date is before T; flagged: the OA text may be a later corrected version."""
    rec = rec or epmc_record(f"PMCID:{pmcid}") or {}
    fp = rec.get("firstPublicationDate")
    if not fp:
        return refuse("REFUSED", f"{pmcid}: first publication date unknown (Europe PMC): full text not read")
    if not before_T(fp):
        return refuse("REFUSED", f"{pmcid}: first published {fp}, on/after T {T}")
    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
    s, ct, d, _ = get(url)
    if s == 200 and d:
        t = xml_to_text(d)
        if len(t) > 3000:
            return dict(write(out, t, "europepmc-xml", url), first_publication_date=fp, warning=LATER)
    return refuse("SOURCE-UNAVAILABLE", f"{pmcid}: no Europe PMC full-text XML")


RXIV_HOSTS = {"biorxiv": "www.biorxiv.org", "medrxiv": "www.medrxiv.org"}


def via_rxiv(doi, out):
    """bioRxiv / medRxiv: the version is pinned on api.biorxiv.org (last posted before T). Its full text (PDF, JATS XML) is served only by
    www.biorxiv.org / www.medrxiv.org, never called (robots.txt disallows AI crawlers; plugins/biology.md); the Europe PMC copy of a preprint
    is of unknown version. So: no full text, the reason names the version; the verifier reads that version's abstract through the gateway."""
    doi = re.sub(r"v\d+$", "", doi.strip().lower())
    for server in (["medrxiv", "biorxiv"] if len(doi.rsplit(".", 1)[-1]) == 8 else ["biorxiv", "medrxiv"]):
        s, ct, d, _ = get(f"https://api.biorxiv.org/details/{server}/{doi}/na/json")
        if s != 200:
            return refuse("SOURCE-UNAVAILABLE", f"api.biorxiv.org answered {s or ct[:60]}: versions not datable, nothing read")
        coll = sorted(json.loads(d).get("collection") or [], key=lambda v: int(v["version"]) if str(v.get("version", "")).isdigit() else 0)
        if not coll:
            continue
        seen = [v for v in coll if before_T(v.get("date"))]
        if not seen:
            return refuse("REFUSED", f"no {server} version of {doi} posted before T {T} (v1: {coll[0].get('date')})", server=server)
        v = seen[-1]
        return refuse("SOURCE-UNAVAILABLE", f"{server} v{v.get('version')} ({v.get('date')}) is the last version before T; its full text is only "
                      f"on {RXIV_HOSTS[server]} (robots.txt disallows AI crawlers, never called): no legitimate version-pinned copy, abstract of "
                      "that version through the gateway", server=server, version="v" + str(v.get("version")), version_date=v.get("date"),
                      versions_total=len(coll), later_versions_masked=len(seen) < len(coll))
    return refuse("SOURCE-UNAVAILABLE", f"{doi}: not found on api.biorxiv.org")


def via_doi(doi, out):
    m = re.match(r"10\.48550/arxiv\.(.+)", doi, re.I)
    if m:
        return via_arxiv(m.group(1), out)
    if re.match(r"10\.(1101|64898)/(\d{4}\.\d{2}\.\d{2}\.)?\d{6,8}(v\d+)?$", doi):
        return via_rxiv(doi, out)        # terminal: Europe PMC / Unpaywall would serve the latest or the published version
    last = None
    rec = None if PDF_ONLY else epmc_record(f'DOI:"{doi}"')
    if rec:
        r = via_epmc(rec["pmcid"], out, rec)
        if ok(r):
            return r
        last = r
    if not CONTACT:  # Unpaywall requires a contact address: set VP_CONTACT to enable this step
        return last
    s, ct, d, _ = get(f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email={urllib.parse.quote(CONTACT)}")
    if s != 200:
        return last
    u = json.loads(d)
    locs = [l for l in [u.get("best_oa_location")] + (u.get("oa_locations") or []) if l]
    tried = set()
    for loc in locs:
        for url in (loc.get("url_for_landing_page"), loc.get("url_for_pdf"), loc.get("url")):
            a = re.search(r"arxiv\.org/(?:abs|pdf)/([^/?#v]+(?:v\d+)?)", url or "")
            p = None if a else re.search(r"(PMC\d+)", url or "")
            k = (a or p) and (a or p).group(1)
            if not k or k in tried:
                continue
            tried.add(k)
            r = via_arxiv(k, out) if a else via_epmc(k, out)     # arXiv: version pinned before T, whatever the journal date; PMC: its date rule
            if ok(r):
                return r
            last = r or last
    pd = u.get("published_date")
    if not before_T(pd):    # a publisher or repository copy is dated by the article: published on/after T or undated -> not read
        return refuse("REFUSED", f"{doi}: published {pd or 'date unknown'} (Unpaywall), not before T {T}: publisher copy not read") if locs else last
    for loc in locs:
        for url in (loc.get("url_for_pdf"), loc.get("url_for_landing_page")):
            if not url or re.search(r"arxiv\.org/|(bio|med)rxiv\.org/|PMC\d+", url):
                continue    # arXiv and PMC copies: only through their version / date rule above; bioRxiv / medRxiv hosts: never called
            s, ct, d, final = get(url)
            if s == 200 and d.startswith(b"%PDF"):
                return dict(write_pdf(out, d, "unpaywall-pdf", final), published_date=pd, oa_version=loc.get("version"), warning=LATER)
            if s == 200 and "html" in ct:
                t = html_to_text(d)
                if len(t) > 15000:  # publisher page with the full text, not a mere abstract
                    return dict(write(out, t, "unpaywall-html", final), published_date=pd, oa_version=loc.get("version"), warning=LATER)
    return last


def write(out, text, method, url):
    with open(os.path.join(out, "source.txt"), "w") as f: f.write(text)
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
    with open(path, "wb") as f: f.write(data)
    text = pdf_to_text(path)
    if len(text) > 3000:
        with open(os.path.join(out, "source.txt"), "w") as f: f.write(text)
        return {"status": "OK", "method": method + "-text", "url": url, "chars": len(text),
                "note": "text extracted from the PDF (pypdf): tables and formulas possibly out of order"}
    return {"status": "OK-PDF", "method": method, "url": url, "bytes": len(data),
            "note": "no extractable text (scan, or pypdf not installed): the agent reads source.pdf directly"}


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--arxiv"); g.add_argument("--doi"); g.add_argument("--pmcid")
    ap.add_argument("--out", required=True)
    ap.add_argument("--T", default=None, help="date of the question YYYY-MM-DD: only versions dated before T are read; absent -> no full text")
    ap.add_argument("--pdf-only", action="store_true", help="use only the PDF (sources available as PDF only)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    mp = os.path.join(a.out, "meta.json")
    try:
        with open(mp) as f: m = json.load(f)
    except (OSError, ValueError):
        m = {}
    if str(m.get("status", "")).startswith("OK") and m.get("T") and m.get("T") == a.T and m.get("T_rule") and m.get("id") == (a.arxiv or a.doi or a.pmcid):
        print(json.dumps(m, ensure_ascii=False)); return
    for f in ("source.txt", "source.pdf"):          # a copy fetched for another T (or before the T rule) is never reused
        if os.path.exists(os.path.join(a.out, f)):
            os.remove(os.path.join(a.out, f))
    t0 = time.time()
    global PDF_ONLY, T
    PDF_ONLY = a.pdf_only
    try:
        T = dt.date.fromisoformat(a.T[:10]) if a.T else None
    except ValueError:
        T = None
    if T is None:
        r = refuse("REFUSED", "no valid date T: full text refused (the latest versions may postdate the question); abstract only, through the gateway")
    else:
        r = (via_arxiv(a.arxiv, a.out) if a.arxiv else via_epmc(a.pmcid, a.out) if a.pmcid else via_doi(a.doi, a.out))
        r = r or refuse("SOURCE-UNAVAILABLE", "no usable free copy found")
    r.update({"id": a.arxiv or a.doi or a.pmcid, "T": a.T, "T_rule": "versions dated before T only", "seconds": round(time.time() - t0, 1)})
    with open(mp, "w") as f: json.dump(r, f, ensure_ascii=False, indent=1)
    print(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    main()
