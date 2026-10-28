#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Context capsule of a local git repository X pinned at one commit SHA (plugins/code.md). Reads the tree at that
SHA only (git ls-tree / show / grep on the commit, never the working copy) and never imports or executes any code of X: every
parser is lexical (regex, tomllib, json). Writes <dir>/capsule-<X>@<sha12>.md (bounded) and .json (complete up to element caps);
intention, refusals and target seam are left to the owner. With --auto (plugins/code.md, "Capsule built from the request"), X is the given
path or its nearest parent holding .git, the SHA defaults to HEAD (frozen), the intention is the request itself ("inferred from the request"),
1 to 3 seams are proposed from the module map ("proposed, not reviewed"), refusals stay empty ("none recorded: implicit authorisation"), Y is
the first GitHub URL of the request (or --y) at --y-sha or at HEAD of the bare repository --y-repo; outputs are <dir>/capsule.md and .json.
Exit: 0 written; 2 refused ({"refusal", "detail"} on stdout; --auto without a local git repository: "capsule_missing"); 3 git failed."""
import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tomllib

OWNER, SHA_RE = "TO BE FILLED BY THE OWNER", re.compile(r"^[0-9a-f]{40}$")
MAX_FILE_BYTES, MAX_REGISTRY_LINES = 4096, 500  # bound on any text read from X; line cap of the registry
REGISTRY_NAMES = ("contributions.jsonl", "apports.jsonl", "registre-apports.jsonl")  # default registry file names looked up at the SHA
MARKERS = {"__init__.py": "python", "package.json": "javascript", "Cargo.toml": "rust", "go.mod": "go"}
TEST_FILE_RE = re.compile(r"(^|/)(test_[^/]*\.py|[^/]*_test\.py|[^/]*\.test\.[^/]+)$")
ENTRY_RE = re.compile(r"""^\s*["']?([\w.-]+)["']?\s*=\s*["']?([\w.]+:[\w.]+)""")  # name = module:function
MAKE_TARGET_RE = re.compile(r"^([A-Za-z0-9_][\w./%-]*)\s*:(?!=)")
LICENSE_KEY_RE = re.compile(r"^\[project\][ \t]*\n(?:[ \t]*[^\[\s][^\n]*\n|[ \t]*\n)*?[ \t]*license\s*=\s*(.+?)[ \t]*$", re.M)  # fallback, truncated pyproject: [project] only
SPDX_HINTS = (("GNU AFFERO", "AGPL-3.0"), ("GNU LESSER", "LGPL"), ("GNU GENERAL PUBLIC", "GPL"), ("APACHE", "Apache-2.0"), ("MOZILLA PUBLIC", "MPL-2.0"),
              ("PERMISSION IS HEREBY GRANTED", "MIT"), ("MIT", "MIT"), ("REDISTRIBUTION AND USE IN SOURCE AND BINARY FORMS", "BSD"), ("BSD", "BSD"), ("ISC", "ISC"))

AUTO_INTENT, AUTO_SEAM, AUTO_REFUSALS = "inferred from the request", "proposed, not reviewed", "none recorded: implicit authorisation"
AUTO_BUILT = "engine (--auto), from the request; not reviewed by the owner"
MAX_SEAMS, MAX_QUESTION_CHARS = 3, 2000
GITHUB_RE = re.compile(r"(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9_.-]{1,100})", re.I)
SOURCE_EXT = (".py", ".js", ".mjs", ".ts", ".go", ".rs", ".rb", ".java", ".c", ".h", ".cpp", ".cs", ".php", ".sh")
NOT_SEAM_PARTS = {"test", "tests", "testing", "docs", "doc", "examples", "example", "benchmarks", "bench", "vendor", "third_party", "node_modules", ".github"}
STOPWORDS = set("the and for with that this from into does what which interesting interest contribution contributions project repo repository "
                "current directory could would should about have has are was were can our your mine github com https http www bring take borrow".split())

class Refusal(Exception):
    def __init__(self, code, rc=2, **detail):
        self.code, self.rc, self.detail = code, rc, detail

def git(repo, *args, ok=(0,)):  # the only subprocess: `git` with literal arguments (no checkout, hence no hook)
    try:
        p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Refusal("git_failed", 3, detail=str(exc)[:500], command=list(args)) from None
    if p.returncode not in ok:
        raise Refusal("git_failed", 3, detail=p.stderr.decode("utf-8", "replace")[:500], command=list(args))
    return p

def open_repo(repo_arg, sha):
    if not SHA_RE.match(sha):  # checked before any subprocess
        raise Refusal("sha_format", detail="--sha must be exactly 40 lowercase hex characters", sha=sha)
    if not (given := pathlib.Path(repo_arg)).exists() or str(repo := given.resolve(strict=True)) != os.path.abspath(repo_arg) or not (repo / ".git").exists():
        raise Refusal("not_a_git_repository", detail="missing, symbolic link on the path, or no .git entry", repo=repo_arg)
    p = git(repo, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}", ok=(0, 1, 128))
    if b"not a git repository" in p.stderr:
        raise Refusal("not_a_git_repository", detail=p.stderr.decode("utf-8", "replace")[:500], repo=repo_arg)
    if p.returncode or p.stdout.strip() != sha.encode():  # a tag SHA is refused too: the capsule pins a commit
        raise Refusal("unknown_sha", detail="not a commit SHA of this repository (give the commit, not a tag). " + p.stderr.decode("utf-8", "replace")[:400], sha=sha)
    return repo

def read_tree(repo, sha):  # (sha256 of the ls-tree output, [(path, size)] of the blobs) at the SHA
    raw = git(repo, "ls-tree", "-r", "-l", "-z", sha).stdout
    return hashlib.sha256(raw).hexdigest(), [(p.decode("utf-8", "replace"), int(m.split()[3])) for m, p in (e.split(b"\t", 1) for e in raw.split(b"\0") if e) if m.split()[1] == b"blob"]

def map_modules(blobs, max_modules):
    found = {p.rpartition("/")[0]: MARKERS[p.rpartition("/")[2]] for p, _ in blobs if p.rpartition("/")[2] in MARKERS}
    items = []
    for d, lang in sorted(found.items(), key=lambda x: (x[1], x[0])):
        inside = [s for p, s in blobs if p.startswith(d + "/" if d else "")]  # nested modules count their files too
        items.append({"path": d or ".", "language": lang, "files": len(inside), "bytes": sum(inside)})
    return {"list": items[:max_modules], "total": len(items), "truncated": len(items) > max_modules}

def map_entry_points(repo, sha, blobs):
    points, limits = [], []
    def cite(path, line, kind, text):
        points.append({"type": kind, "where": f"{path}:{line}@{sha[:12]}", "text": text.strip()[:200]})
    for path, size in blobs:
        base = path.rpartition("/")[2]
        if base == "__main__.py":
            cite(path, 1, "__main__", "python -m <package>")
        if base not in ("pyproject.toml", "setup.py", "setup.cfg", "package.json", "Makefile") and not base.startswith("Dockerfile") and not path.startswith("bin/"):
            continue
        text, parsed = git(repo, "show", f"{sha}:{path}").stdout[:MAX_FILE_BYTES].decode("utf-8", "replace"), None  # bounded blob text at the SHA; the working copy is never read
        if size > MAX_FILE_BYTES:
            limits.append(f"{path}: read truncated at {MAX_FILE_BYTES} bytes")
        lines = text.splitlines()
        try:
            if base == "pyproject.toml":
                proj = tomllib.loads(text).get("project", {})
                parsed = {"scripts": proj.get("scripts", {}), **proj.get("entry-points", {})}
            elif base == "package.json":
                pkg = json.loads(text)
                parsed = {"scripts": pkg.get("scripts", {}), "bin": pkg["bin"] if isinstance(pkg.get("bin"), dict) else
                          {pkg.get("name", "bin"): pkg["bin"]} if "bin" in pkg else {}}
        except (tomllib.TOMLDecodeError, ValueError, TypeError, AttributeError):  # invalid, truncated, or not a table
            limits.append(f"{path}: not parsed (truncated or invalid), lexical fallback only")
        for group, table in (parsed or {}).items():
            for name, target in (table.items() if isinstance(table, dict) else ()):
                line = next((i for i, ln in enumerate(lines, 1) if ln.lstrip().strip("\"'").startswith(str(name))), 0)
                cite(path, line, f"{base} {group}", f"{name} = {target}")
        for i, ln in enumerate(lines, 1):
            if parsed is None and base in ("pyproject.toml", "setup.py", "setup.cfg") and ENTRY_RE.match(ln):
                cite(path, i, f"{base} entry", ln)
            elif base == "Makefile" and MAKE_TARGET_RE.match(ln):
                cite(path, i, "Makefile target", ln)
            elif base.startswith("Dockerfile") and re.match(r"\s*(ENTRYPOINT|CMD)\b", ln):
                cite(path, i, "Dockerfile", ln)
            elif path.startswith("bin/") and i == 1 and ln.startswith("#!"):
                cite(path, 1, "bin shebang", ln)
    out = git(repo, "grep", "-n", "-z", "-I", "-F", "-e", 'if __name__ == "__main__"', "-e", "if __name__ == '__main__'",  # both quote styles
              sha, "--", "*.py", "bin/*", ok=(0, 1)).stdout
    for hit in (h for h in out.split(b"\n") if h.count(b"\0") >= 2):
        where, line, text = hit.split(b"\0", 2)
        cite(where[41:].decode("utf-8", "replace"), int(line), "__name__ guard", text.decode("utf-8", "replace"))
    limits.append("lexical parsers only: entry points computed at runtime (dynamic setup.py) are not seen")
    return {"list": sorted(points, key=lambda p: (p["where"], p["type"])), "limits": limits}

def map_tests(blobs):
    dirs, total = {}, 0
    for path, _ in blobs:
        total += (is_test := 1 if TEST_FILE_RE.search(path) else 0)
        parts = path.split("/")[:-1]
        if key := next(("/".join(parts[: i + 1]) for i, part in enumerate(parts) if part in ("test", "tests")), None):
            dirs[key] = dirs.get(key, 0) + is_test
    return {"directories": [{"path": d, "test_files": n} for d, n in sorted(dirs.items())], "test_files": total}

def guess_spdx(text):  # a guess by name, never a reading of the licence
    return next((spdx for hint, spdx in SPDX_HINTS if hint in text.upper()), None)

def map_license(repo, sha, blobs):
    root = sorted(p for p, _ in blobs if "/" not in p)
    for path in (p for p in root if p.startswith(("LICENSE", "COPYING"))):
        text = git(repo, "show", f"{sha}:{path}").stdout[:MAX_FILE_BYTES].decode("utf-8", "replace")
        return {"file": path, "first_line": next((ln.strip() for ln in text.splitlines() if ln.strip()), "")[:200], "spdx_guess": guess_spdx(text)}
    for path in (p for p in ("pyproject.toml", "package.json") if p in root):
        text = git(repo, "show", f"{sha}:{path}").stdout[:MAX_FILE_BYTES].decode("utf-8", "replace")
        try:  # top-level key only: a nested "license" (dependencies...) is not the package licence
            val = (tomllib.loads(text).get("project", {}) if path == "pyproject.toml" else json.loads(text)).get("license")
        except (tomllib.TOMLDecodeError, ValueError, TypeError, AttributeError):  # truncated or invalid: lexical fallback
            val = path == "pyproject.toml" and (m := LICENSE_KEY_RE.search(text)) and m.group(1)
        if val:
            return {"file": path, "first_line": str(val)[:200], "spdx_guess": guess_spdx(str(val))}
    return None

def read_registry(repo, sha, blobs, arg):  # lines copied verbatim, parsed only to validate; no field interpreted
    paths = {p for p, _ in blobs}
    arg = arg or next((c for c in REGISTRY_NAMES if c in paths), None)
    if arg is None:
        return None, []
    if arg in paths:  # a path inside X, read at the SHA
        raw, source = git(repo, "show", f"{sha}:{arg}").stdout, f"{arg}@{sha[:12]}"
    elif pathlib.Path(arg).is_file():  # outside the tree: pinned by content, not by the SHA
        raw, source = (b := pathlib.Path(arg).read_bytes()), f"{pathlib.Path(arg).resolve()} sha256={hashlib.sha256(b).hexdigest()}"
    else:
        raise Refusal("registry_not_found", detail="neither a path in X at the SHA nor a file", registry=arg)
    lines, entries = [(n, ln) for n, ln in enumerate(raw.decode("utf-8", "replace").splitlines(), 1) if ln.strip()], []  # n: physical line
    for n, line in lines:
        try:
            entries.append(json.loads(line))
        except ValueError as exc:
            raise Refusal("registry_invalid_jsonl", detail=str(exc)[:200], line=n, source=source) from None
    kept = [ln for _, ln in lines[:MAX_REGISTRY_LINES]]
    return {"source": source, "lines_total": len(lines), "truncated": len(lines) > len(kept), "entries": entries[:len(kept)]}, kept

def find_repo(path_arg):  # --auto: the given path, or its nearest parent holding a .git entry (a path check, no subprocess)
    try:
        start = pathlib.Path(path_arg).resolve(strict=True)
    except OSError:
        start = None
    for d in ([start, *start.parents] if start and start.is_dir() else []):
        if (d / ".git").exists():
            return str(d)
    raise Refusal("capsule_missing", detail="no local git repository for X: give the path of your project (a git repository with at least one commit), "
                  "or ask from inside it; nothing was collected", repo=path_arg)

def head_sha(repo, what="X"):  # HEAD frozen at the request: the commit, never the working copy
    p = git(repo, "rev-parse", "--verify", "--quiet", "HEAD^{commit}", ok=(0, 1, 128))
    sha = p.stdout.decode().strip()
    if p.returncode or not SHA_RE.match(sha):
        raise Refusal("capsule_missing" if what == "X" else "y_sha_unresolved", detail=f"{what}: no commit at HEAD (an empty repository cannot be pinned)", repo=str(repo))
    return sha

def parse_y(question, y_arg):  # "owner/repo" from --y, else the first GitHub URL of the request; None = need only
    m = GITHUB_RE.search(y_arg or question or "")
    if y_arg and not m:
        raise Refusal("y_not_github", detail="--y must be a GitHub repository URL (https://github.com/<owner>/<repo>)", y=y_arg)
    return m and f"{m.group(1)}/{re.sub(r'(?i)[.]git$', '', m.group(2)).rstrip('.')}"

def resolve_y(y, y_sha, y_repo):  # Y@SHA: the SHA given (read by the engine through the gateway) or HEAD of the bare repository supplied by the host
    if not y:
        return None
    if y_sha:
        if not SHA_RE.match(y_sha):
            raise Refusal("sha_format", detail="--y-sha must be exactly 40 lowercase hex characters", sha=y_sha)
        return {"repo": f"github.com/{y}", "sha": y_sha, "sha_source": "given by the engine (gateway reading)", "licence": "to read"}
    if y_repo:
        if not pathlib.Path(y_repo).is_dir():
            raise Refusal("y_repo_missing", detail="--y-repo is not a directory", y_repo=y_repo)
        return {"repo": f"github.com/{y}", "sha": head_sha(y_repo, "Y"), "sha_source": f"HEAD of the default branch in the bare repository supplied by the host ({y_repo})",
                "licence": "to read"}
    return {"repo": f"github.com/{y}", "sha": None, "sha_source": "to resolve: HEAD of the default branch at the request date, through the gateway", "licence": "to read"}

def question_words(question):
    return {w for w in re.findall(r"[a-z][a-z0-9]{2,}", GITHUB_RE.sub(" ", (question or "").lower())) if w not in STOPWORDS}

DEF_RE = r"^(def |class |async def |function |export function |export class |func |pub fn |fn )"  # first top-level definition: the line cited for a file seam

def propose_seams(repo, doc, blobs, sha, question):  # 1 to 3 seams from the module map: a hint for the engine, never a reading of X
    words, s12, eps = question_words(question), sha[:12], doc["entry_points"]["list"]
    def usable(path):
        return not (set(path.lower().split("/")) & NOT_SEAM_PARTS)
    def score(path):
        return len(words & set(re.split(r"[/_.-]+", path.lower())))
    mods = sorted((m for m in doc["modules"]["list"] if usable(m["path"])), key=lambda m: (-score(m["path"]), -m["bytes"], m["path"]))
    files = [(p, size) for p, size in blobs if p.endswith(SOURCE_EXT) and usable(p)]
    picks = []  # (path, line or None, why); per module: its entry point, else its largest source file; then the next largest files of the ranked modules
    for m in mods:
        prefix = "" if m["path"] == "." else m["path"] + "/"
        ep = next((e for e in eps if prefix and e["where"].startswith(prefix) and usable(e["where"].split(":")[0])), None)
        mine = sorted(((-sz, p) for p, sz in files if p.startswith(prefix) and "/" not in p[len(prefix):]), key=lambda t: (-score(t[1]), t))
        tag = f"module {m['path']} ({m['language']}, {m['files']} files, {m['bytes']} bytes)"
        if ep:
            path, line = ep["where"].split("@")[0].rsplit(":", 1)
            picks.append((path, int(line), f"{tag}; entry point: {ep['type']}"))
        picks += [(p, None, f"{tag}; source file of {-sz} bytes") for sz, p in mine]
    if not mods:  # no module marker: entry points, then the largest source files of the tree
        for e in eps:
            if usable(e["where"].split(":")[0]):
                path, line = e["where"].split("@")[0].rsplit(":", 1)
                picks.append((path, int(line), f"entry point: {e['type']}"))
        picks += [(p, None, f"source file of {sz} bytes; no module marker in X") for p, sz in sorted(files, key=lambda t: (-score(t[0]), -t[1], t[0]))]
    chosen, seen = [], set()
    for path, line, why in picks:
        if path not in seen and len(chosen) < MAX_SEAMS:
            seen.add(path)
            chosen.append([path, line, why])
    need = [c[0] for c in chosen if c[1] is None]
    hits = git(repo, "--literal-pathspecs", "grep", "-n", "-z", "-I", "-E", "-e", DEF_RE, sha, "--", *need, ok=(0, 1)).stdout if need else b""
    first = {}
    for hit in (h for h in hits.split(b"\n") if h.count(b"\0") >= 2):
        where, line, _ = hit.split(b"\0", 2)
        first.setdefault(where[41:].decode("utf-8", "replace"), int(line))
    return [{"where": f"{path}:{line or first.get(path, 1)}@{s12}", "why": why + ("" if line or path not in first else "; first top-level definition"), "status": AUTO_SEAM}
            for path, line, why in chosen]

def auto_fields(repo, doc, blobs, sha, question, y, request_date):
    q = " ".join((question or "").split())[:MAX_QUESTION_CHARS]
    if not q:
        raise Refusal("question_missing", detail="--auto needs --question: the request, word for word")
    doc.update({"target_seam": propose_seams(repo, doc, blobs, sha, q), "target_seam_status": AUTO_SEAM, "intention": q, "intention_status": AUTO_INTENT,
                "refusals": [], "refusals_status": AUTO_REFUSALS, "reviewed_by_owner": "no", "built_by": AUTO_BUILT,
                "request_date": request_date or dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                "mode": "Y given" if y else "need only", "Y": y or "none (need only)"})
    return doc

def build(repo_arg, sha, registry, max_modules, max_bytes=65536):
    if max_modules < 0 or max_bytes < 256:
        raise Refusal("bound_invalid", detail="--max-modules >= 0 and --max-bytes >= 256 required", max_modules=max_modules, max_bytes=max_bytes)
    tree_sha, blobs = read_tree(repo := open_repo(repo_arg, sha), sha)
    reg, raw_lines = read_registry(repo, sha, blobs, registry)
    doc = {"target_seam": OWNER, "intention": OWNER, "refusals": [OWNER], "reviewed_by_owner": "no", "mode": OWNER, "Y": OWNER, "request_date": OWNER,
           "identity": {"repo": str(repo), "sha": sha, "tree_sha256": tree_sha, "files": len(blobs), "bytes": sum(s for _, s in blobs),
                        "commit_date": git(repo, "show", "-s", "--format=%cI", sha).stdout.decode().strip()},
           "license": map_license(repo, sha, blobs), "modules": map_modules(blobs, max_modules),
           "entry_points": map_entry_points(repo, sha, blobs), "tests": map_tests(blobs), "registry": reg,
           "meta": {"generated_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "tool": "code_capsule.py"}}
    return doc, raw_lines

def render_markdown(doc, raw_lines, max_bytes):
    ident, lic, mods, pe, reg = doc["identity"], doc["license"], doc["modules"], doc["entry_points"], doc["registry"]
    if doc.get("built_by") == AUTO_BUILT:
        y = doc["Y"]
        y_line = (f"- Y: {y['repo']}@{y['sha'] or 'unresolved'} ({y['sha_source']}), licence read: {y['licence']}" if isinstance(y, dict) else f"- Y: {y}")
        seams = [f"  - {s['where']} - {s['why']}" for s in doc["target_seam"]] or ["  - none proposed (no module, entry point or source file found at this SHA)"]
        own = [f"# Context capsule: {pathlib.Path(ident['repo']).name}@{ident['sha'][:12]}", "", "## Built from the request (capsule not reviewed)", "",
               f"- reviewed_by_owner: no (built by {AUTO_BUILT}; the report is labelled \"capsule not reviewed\")",
               f"- X: {pathlib.Path(ident['repo']).name}@{ident['sha']} (HEAD frozen at the request; uncommitted changes are not part of X)",
               f"- request_date: {doc['request_date']} (= T)", f"- target_seam: ({AUTO_SEAM}; from the module map, 1 to 3)", *seams,
               f"- intention: \"{doc['intention']}\" ({AUTO_INTENT})", f"- refusals: {AUTO_REFUSALS}", f"- mode: {doc['mode']}", y_line, "",
               "Review by the owner: plugins/code.md, section Context capsule (5 points); a reviewed capsule replaces this one.", ""]
    head = [f"# Context capsule: {pathlib.Path(ident['repo']).name}@{ident['sha'][:12]}", "", "## To fill before use", "",
            f"- target_seam: {doc['target_seam']}  (1 to 3 seams, path:line@SHA on the X side, what happens there today)",
            f"- intention: {doc['intention']}  (measurable: throughput, invariant, guarantee, cost)",
            f"- refusals: {', '.join(doc['refusals'])}  (core, Gate, licences, dependencies; a missing refusal = implicit permission)",
            f"- reviewed_by_owner: no ({OWNER}: yes + date after review)", f"- request_date: {doc['request_date']} (= T)", f"- mode: {doc['mode']} (Y given | need only)", f"- Y: {doc['Y']} (repository@SHA, licence read)", "",
            "Review by the owner: plugins/code.md, section Context capsule (5 points). Not reviewed = report labelled \"capsule not reviewed\".", "",
            "## Identity", "", f"- X: {ident['repo']}@{ident['sha']}", f"- commit_date: {ident['commit_date']}", f"- tree_sha256: {ident['tree_sha256']}",
            f"- files: {ident['files']}; bytes: {ident['bytes']}", "", "## License", "", "- LICENSE MISSING: read before any borrowing" if not lic else
            f"- {lic['file']}: \"{lic['first_line']}\", guessed SPDX: {lic['spdx_guess'] or 'unknown'} (to read before any borrowing)", "",
            f"## Seam map ({mods['total']} modules{'; list truncated' if mods['truncated'] else ''})", "", "| language | module | files | bytes |", "|---|---|---|---|"]
    if doc.get("built_by") == AUTO_BUILT:
        head = own + head[head.index("## Identity"):]
    mod_lines = [f"| {m['language']} | {m['path']} | {m['files']} | {m['bytes']} |" for m in mods["list"]]
    pe_lines = [f"- {p['type']}: `{p['where']}`: `{p['text']}`" for p in pe["list"]]
    mid = [""] + [f"Limit: {lim}" for lim in pe["limits"]] + ["", "## Tests", ""]
    mid += [f"- {t['path']}/: {t['test_files']} test files" for t in doc["tests"]["directories"]] + [f"- total test files: {doc['tests']['test_files']}", "", "## Contribution registry", ""]
    mid += ([f"Source: {reg['source']}; {reg['lines_total']} lines{' (truncated)' if reg['truncated'] else ''}; copied as is.", "", "```jsonl"]
            if reg else [f"No registry ({' / '.join(REGISTRY_NAMES)} missing at this SHA, --registry not given)."])
    tail, pe_head = (["```", ""] if reg else [""]) + ["## Meta", "", f"- generated_utc: {doc['meta']['generated_utc']}; tool: {doc['meta']['tool']}", ""], ["", "## Entry points", ""]
    size = sum(len(ln.encode()) + 1 for ln in head + mod_lines + pe_head + pe_lines + mid + raw_lines + tail)
    for items in (raw_lines, mod_lines, pe_lines):  # registry first, then the map, then entry points, until the bound holds
        hidden = 0
        while size > max_bytes and items:
            size, hidden = size - len(items.pop().encode()) - 1, hidden + 1
        if hidden:
            items.append(f"... (truncated: {hidden} items not shown)")
            size += len(items[-1].encode()) + 1
    text = "\n".join(head + mod_lines + pe_head + pe_lines + mid + raw_lines + tail)
    if len(text.encode()) > max_bytes:  # last resort: even the fixed part exceeds the bound
        text = text.encode()[: max_bytes - 48].decode("utf-8", "ignore").rsplit("\n", 1)[0] + "\n... (truncated: --max-bytes bound reached)\n"
    return text

def main(argv=None):
    ap = argparse.ArgumentParser(description="Context capsule of a local git repository X at a 40-hex SHA (read-only, nothing of X is executed). --registry: a path "
                                 "inside X at the SHA, else a file (default: contributions.jsonl at the SHA). --out: output directory (default .). --max-bytes bounds the Markdown only.")
    for flag, kw in (("--repo", {"required": True}), ("--sha", {}), ("--registry", {}), ("--out", {"default": "."}),
                     ("--max-bytes", {"type": int, "default": 65536}), ("--max-modules", {"type": int, "default": 200}),
                     ("--auto", {"action": "store_true", "help": "build the capsule from the request (--question): X = --repo or its nearest parent with .git, SHA = HEAD"}),
                     ("--question", {"help": "the request, word for word (--auto)"}), ("--y", {"help": "GitHub URL of Y (--auto; default: first GitHub URL of --question)"}),
                     ("--y-sha", {"help": "40-hex SHA of Y read by the engine (--auto)"}), ("--y-repo", {"help": "bare repository of Y supplied by the host: Y@SHA = its HEAD (--auto)"}),
                     ("--request-date", {"help": "ISO date of the request = T (--auto; default: now, UTC)"})):
        ap.add_argument(flag, **kw)
    a = ap.parse_args(argv)
    if not a.auto and not a.sha:
        ap.error("--sha is required (or --auto, which freezes HEAD)")
    try:
        if a.auto:
            a.repo = find_repo(a.repo)
            a.sha = head_sha(a.repo) if a.sha in (None, "HEAD") else a.sha
            y = resolve_y(parse_y(a.question, a.y), a.y_sha, a.y_repo)
        doc, raw_lines = build(a.repo, a.sha, a.registry, a.max_modules, a.max_bytes)
        if a.auto:
            if (pathlib.Path(a.out) / "capsule.md").exists() or (pathlib.Path(a.out) / "capsule.json").exists():
                raise Refusal("capsule_exists", detail="a capsule is already in the working directory: it is used as is, never overwritten", out=a.out)
            auto_fields(pathlib.Path(a.repo), doc, read_tree(pathlib.Path(a.repo), a.sha)[1], a.sha, a.question, y, a.request_date)
    except Refusal as r:
        print(json.dumps({"refusal": r.code, **r.detail}, ensure_ascii=False, sort_keys=True))
        return r.rc
    pathlib.Path(a.out).mkdir(parents=True, exist_ok=True)
    stem = str(pathlib.Path(a.out) / ("capsule" if a.auto else f"capsule-{pathlib.Path(doc['identity']['repo']).name}@{a.sha[:12]}"))  # no with_suffix: X may contain dots
    pathlib.Path(stem + ".md").write_text(md := render_markdown(doc, raw_lines, a.max_bytes), encoding="utf-8")
    pathlib.Path(stem + ".json").write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    res = {"markdown": stem + ".md", "json": stem + ".json", "markdown_bytes": len(md.encode())}
    if a.auto:
        res.update({"X": f"{doc['identity']['repo']}@{a.sha}", "seams_proposed": len(doc["target_seam"]), "mode": doc["mode"], "label": "capsule not reviewed",
                    "Y": f"{y['repo']}@{y['sha'] or 'unresolved'}" if y else None,
                    "question_to_owner": "Anything in X that must not be touched (core, files, licences, dependencies)? Interactive session only; no answer = continue."})
    print(json.dumps(res, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    sys.exit(main())
