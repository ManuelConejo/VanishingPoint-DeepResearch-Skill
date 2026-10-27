#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Context capsule of a local git repository X pinned at one commit SHA (plugins/code.md). Reads the tree at that
SHA only (git ls-tree / show / grep on the commit, never the working copy) and never imports or executes any code of X: every
parser is lexical (regex, tomllib, json). Writes <dir>/capsule-<X>@<sha12>.md (bounded) and .json (complete up to element caps);
intention, refusals and target seam are left to the owner. Exit: 0 written; 2 refused ({"refusal", "detail"} on stdout); 3 git failed."""
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
    out = git(repo, "grep", "-n", "-z", "-I", "-F", "-e", 'if __name__ == "__main__"', sha, "--", "*.py", "bin/*", ok=(0, 1)).stdout
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
    for flag, kw in (("--repo", {"required": True}), ("--sha", {"required": True}), ("--registry", {}), ("--out", {"default": "."}),
                     ("--max-bytes", {"type": int, "default": 65536}), ("--max-modules", {"type": int, "default": 200})):
        ap.add_argument(flag, **kw)
    a = ap.parse_args(argv)
    try:
        doc, raw_lines = build(a.repo, a.sha, a.registry, a.max_modules, a.max_bytes)
    except Refusal as r:
        print(json.dumps({"refusal": r.code, **r.detail}, ensure_ascii=False, sort_keys=True))
        return r.rc
    pathlib.Path(a.out).mkdir(parents=True, exist_ok=True)
    stem = str(pathlib.Path(a.out) / f"capsule-{pathlib.Path(doc['identity']['repo']).name}@{a.sha[:12]}")  # no with_suffix: X may contain dots
    pathlib.Path(stem + ".md").write_text(md := render_markdown(doc, raw_lines, a.max_bytes), encoding="utf-8")
    pathlib.Path(stem + ".json").write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"markdown": stem + ".md", "json": stem + ".json", "markdown_bytes": len(md.encode())}))
    return 0

if __name__ == "__main__":
    sys.exit(main())
