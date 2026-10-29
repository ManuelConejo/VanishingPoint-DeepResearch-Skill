# SPDX-License-Identifier: Apache-2.0
"""Tests of code_capsule.py on a throwaway git repository built in tmp_path (two commits; evil.py and pkg/__main__.py raise at
import, which proves that nothing of X is executed). Hermetic: clean environment, throwaway HOME, GIT_CONFIG_GLOBAL=/dev/null.
Runs under pytest (python3 -m pytest -q tests/test_code_capsule.py) or alone with the standard library (python3 -I tests/test_code_capsule.py:
unittest, with a minimal stand-in for the tmp_path / monkeypatch fixtures and pytest.raises)."""
import inspect
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import types
import unittest

try:
    import pytest
except ImportError:                                     # standard library only: the stand-ins below
    class _Raises:
        def __init__(self, exc):
            self.exc, self.value = exc, None

        def __enter__(self):
            return self

        def __exit__(self, typ, val, tb):
            if typ is None:
                raise AssertionError(f"{self.exc.__name__} not raised")
            if not issubclass(typ, self.exc):
                return False
            self.value = val
            return True
    pytest = types.SimpleNamespace(fixture=lambda *a, **k: (lambda f: f), raises=_Raises)

HERE = pathlib.Path(__file__).resolve().parent
TOOLS = HERE.parent / "tools"
EXEC = 'raise SystemExit("executed")\n'
FILES_1 = {"pyproject.toml": '[project]\nname = "pkg"\nlicense = "MIT"\n[project.scripts]\npkg-cli = "pkg:main"\n',
           "pkg/__init__.py": "def main():\n    pass\n", "pkg/__main__.py": EXEC, "tests/test_x.py": "def test_x():\n    pass\n",
           "LICENSE": "MIT License\n\nCopyright (c) 2026\n", "contributions.jsonl": '{"id": "B-001", "status": "adopted"}\n{"id": "B-002", "x": [1, 2]}\n'}
FILES_2 = {"single.py": "if __name__ == '__main__':\n    pass\n", "evil.py": EXEC + '\nif __name__ == "__main__":\n    pass\n', "Makefile": "VAR := 1\n.PHONY: all\nall: build\n\tmake\n",
           "Dockerfile": 'FROM x\nENTRYPOINT ["x"]\n', "bin/run": "#!/bin/sh\necho\n"}
OWNER = "TO BE FILLED BY THE OWNER"


def module():
    sys.path.insert(0, str(TOOLS))
    try:
        import code_capsule
    except ImportError:
        assert False, "code_capsule.py is missing"
    return code_capsule


def _repo(tmp_path, monkeypatch):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path / "home"), "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"}
    (tmp_path / "home").mkdir()
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    r = tmp_path / "x.y"  # a dot in the name: the output names must still be capsule-x.y@<sha12>.md/.json
    r.mkdir()

    def commit(files):
        for name, text in files.items():
            (r / name).parent.mkdir(parents=True, exist_ok=True)
            (r / name).write_text(text)
        for args in (["add", "-A"], ["commit", "-q", "-m", "c"]):
            subprocess.run(["git", "-C", str(r), *args], env=env, check=True, capture_output=True)
        return subprocess.run(["git", "-C", str(r), "rev-parse", "HEAD"], env=env, check=True, capture_output=True, text=True).stdout.strip()

    def run(sha, *extra, env=env):  # CLI under python3 -I, in a clean environment; returns (rc, stdout JSON | text, doc | None)
        out = tmp_path / f"out{len(list(tmp_path.iterdir()))}"
        p = subprocess.run([sys.executable, "-I", str(TOOLS / "code_capsule.py"), "--repo", str(r), "--sha", sha, "--out", str(out), *extra],
                           env=env, capture_output=True, text=True, cwd=tmp_path)
        res = json.loads(p.stdout) if p.stdout.startswith("{") else p.stdout + p.stderr
        return p.returncode, res, (json.loads(pathlib.Path(res["json"]).read_text()) if p.returncode == 0 else None)
    subprocess.run(["git", "-C", str(r), "init", "-q"], env=env, check=True)
    return r, [commit(FILES_1), commit(FILES_2)], commit, run


repo = pytest.fixture(name="repo")(_repo)


def test_refuses_sha_format_before_any_subprocess(repo, tmp_path):
    r, shas, _, run = repo
    (tmp_path / "nogit").mkdir()
    for sha in ("main", "HEAD", shas[0][:7], shas[0].upper(), shas[0] + "0"):
        rc, out, _ = run(sha, env={"PATH": str(tmp_path / "nogit"), "HOME": str(tmp_path)})  # no git on PATH: a subprocess would give rc 3
        assert (rc, out["refusal"]) == (2, "sha_format"), (sha, out)


def test_refuses_unknown_sha_and_non_git_directory(repo, tmp_path):
    r, shas, _, run = repo
    rc, out, _ = run("0" * 40)
    assert (rc, out["refusal"], out["sha"]) == (2, "unknown_sha", "0" * 40), out
    (tmp_path / "plain").mkdir()
    (tmp_path / "link").symlink_to(r)
    cc = module()
    for repo_dir in (tmp_path / "plain", tmp_path / "link", tmp_path / "missing"):
        with pytest.raises(cc.Refusal) as exc:
            cc.open_repo(str(repo_dir), shas[0])
        assert (exc.value.code, exc.value.rc) == ("not_a_git_repository", 2), repo_dir


def test_reads_the_tree_at_sha_not_the_working_copy(repo):
    r, shas, _, run = repo
    before = run(shas[1])[2]
    (r / "pyproject.toml").write_text('[project]\nname = "pkg"\n[project.scripts]\nother = "other:main"\n')  # uncommitted edits
    (r / "LICENSE").unlink()
    (r / "evil.py").write_text("x = 1\n")  # the __name__ guard must still be cited from the tree
    (r / "new" / "__init__.py").parent.mkdir()
    (r / "new" / "__init__.py").write_text("")
    after = run(shas[1])[2]
    for key in ("identity", "license", "modules", "entry_points", "tests", "registry"):
        assert before[key] == after[key], key
    assert any(p["text"] == "pkg-cli = pkg:main" for p in after["entry_points"]["list"]) and after["license"]["file"] == "LICENSE"
    first = run(shas[0])[2]
    assert first["identity"]["tree_sha256"] != after["identity"]["tree_sha256"] and "evil.py" not in json.dumps(first)


def test_never_imports_or_executes_repository_code(repo):
    r, shas, _, run = repo
    rc, res, doc = run(shas[1])
    assert rc == 0 and pathlib.Path(res["markdown"]).is_file() and doc["identity"]["sha"] == shas[1]
    assert res["markdown"].endswith(f"capsule-x.y@{shas[1][:12]}.md") and res["json"].endswith(f"capsule-x.y@{shas[1][:12]}.json")
    cited = {p["where"].split("@")[0] for p in doc["entry_points"]["list"]}
    assert {"evil.py:3", "pkg/__main__.py:1"} <= cited and "evil" not in sys.modules and "pkg" not in sys.modules
    assert module().build(str(r), shas[1], None, 200)[0]["identity"]["sha"] == shas[1]  # in-process: a SystemExit would fail here


def test_maps_modules_entry_points_tests_and_license(repo):
    r, shas, commit, run = repo
    doc = run(shas[1])[2]
    s = shas[1][:12]
    nbytes = sum(len(FILES_1[k].encode()) for k in ("pkg/__init__.py", "pkg/__main__.py"))
    assert doc["modules"] == {"list": [{"path": "pkg", "language": "python", "files": 2, "bytes": nbytes}], "total": 1, "truncated": False}
    got = {(p["type"], p["where"]) for p in doc["entry_points"]["list"]}
    assert got == {("pyproject.toml scripts", f"pyproject.toml:5@{s}"), ("__main__", f"pkg/__main__.py:1@{s}"), ("Makefile target", f"Makefile:3@{s}"),
                   ("Dockerfile", f"Dockerfile:2@{s}"), ("bin shebang", f"bin/run:1@{s}"), ("__name__ guard", f"evil.py:3@{s}"), ("__name__ guard", f"single.py:1@{s}")}, got
    assert doc["tests"] == {"directories": [{"path": "tests", "test_files": 1}], "test_files": 1}
    assert doc["license"] == {"file": "LICENSE", "first_line": "MIT License", "spdx_guess": "MIT"}
    (r / "LICENSE").unlink()
    rc, res, doc3 = run(commit({}))
    assert doc3["license"] == {"file": "pyproject.toml", "first_line": "MIT", "spdx_guess": "MIT"}
    (r / "pyproject.toml").unlink()
    rc, res, doc4 = run(commit({"package.json": '{"name":"p","dependencies":{"license":"MIT"},"license":"ISC","bin":"cli.js"}'}))  # one line, nested key, bin string
    assert doc4["license"] == {"file": "package.json", "first_line": "ISC", "spdx_guess": "ISC"}
    assert any(p["text"] == "p = cli.js" for p in doc4["entry_points"]["list"])
    (r / "package.json").unlink()
    rc, res, doc4 = run(commit({}))
    assert doc4["license"] is None and "LICENSE MISSING: read before any borrowing" in pathlib.Path(res["markdown"]).read_text()


def test_registry_is_copied_verbatim_or_refused_on_invalid_line(repo, tmp_path):
    r, shas, _, run = repo
    rc, res, doc = run(shas[1])
    lines = FILES_1["contributions.jsonl"].splitlines()
    assert doc["registry"] == {"source": f"contributions.jsonl@{shas[1][:12]}", "lines_total": 2, "truncated": False, "entries": [json.loads(ln) for ln in lines]}
    assert all(ln in pathlib.Path(res["markdown"]).read_text() for ln in lines)
    (tmp_path / "bad.jsonl").write_text('{"ok": 1}\n\nnot json\n')
    rc, out, _ = run(shas[1], "--registry", str(tmp_path / "bad.jsonl"))
    assert (rc, out["refusal"], out["line"]) == (2, "registry_invalid_jsonl", 3), out  # physical line number
    (tmp_path / "ok.jsonl").write_text('{"ok": 1}\n')
    assert run(shas[1], "--registry", str(tmp_path / "ok.jsonl"))[2]["registry"]["source"].endswith("/ok.jsonl sha256=" + __import__("hashlib").sha256(b'{"ok": 1}\n').hexdigest())
    assert run(shas[1], "--registry", "absent.jsonl")[1]["refusal"] == "registry_not_found"
    rc, out, _ = run(shas[1], "--registry", "evil.py")  # a path inside X, read at the SHA: not JSON
    assert (rc, out["refusal"], out["line"], out["source"]) == (2, "registry_invalid_jsonl", 1, f"evil.py@{shas[1][:12]}"), out


def test_owner_fields_are_left_to_fill(repo):
    r, shas, _, run = repo
    rc, res, doc = run(shas[1])
    assert (doc["intention"], doc["refusals"], doc["target_seam"], doc["mode"], doc["Y"], doc["request_date"]) == (OWNER, [OWNER], OWNER, OWNER, OWNER, OWNER)
    assert doc["reviewed_by_owner"] == "no"
    md = pathlib.Path(res["markdown"]).read_text()
    assert md.index("## To fill before use") < md.index(f"- target_seam: {OWNER}") < md.index(f"- intention: {OWNER}") < md.index(f"- refusals: {OWNER}") < md.index("- reviewed_by_owner: no") < md.index("## Identity")
    assert "none" not in json.dumps([doc["intention"], doc["refusals"], doc["target_seam"]]).lower()


def test_markdown_respects_max_bytes_and_json_stays_complete(repo):
    r, shas, commit, run = repo
    big = commit({f"m{i:04d}/__init__.py": "" for i in range(1000)})
    rc, res, doc = run(big, "--max-modules", "200", "--max-bytes", "2000")
    md = pathlib.Path(res["markdown"]).read_bytes()
    assert len(md) <= 2000 and "truncated" in md.decode() and res["markdown_bytes"] == len(md)
    assert (len(doc["modules"]["list"]), doc["modules"]["total"], doc["modules"]["truncated"]) == (200, 1001, True)
    assert len(doc["registry"]["entries"]) == 2 and len(doc["entry_points"]["list"]) == 7   # 6 + the single-quoted guard of single.py
    assert run(big, "--max-bytes", "10")[1]["refusal"] == "bound_invalid" and run(big, "--max-modules", "-1")[1]["refusal"] == "bound_invalid"
    full = pathlib.Path(run(big)[1]["markdown"]).read_text()  # default bound: sections in the order of the template, map before entry points
    order = [full.index(h) for h in ("## To fill", "## Identity", "## License", "## Seam map", "| python | m0000 |", "## Entry points", "- __main__", "## Tests", "## Contribution registry", "## Meta")]
    assert len(full.encode()) <= 65536 and order == sorted(order), order


def test_output_is_deterministic_for_the_same_sha(repo):
    r, shas, _, run = repo
    a, b = run(shas[1])[1], run(shas[1])[1]
    ta, tb = pathlib.Path(a["json"]).read_text(), pathlib.Path(b["json"]).read_text()
    da, db = json.loads(ta), json.loads(tb)
    assert da.pop("meta")["tool"] == db.pop("meta")["tool"] and da == db
    assert ta == json.dumps(json.loads(ta), ensure_ascii=False, sort_keys=True, indent=1) + "\n"  # sorted keys, timestamp only in meta
    today = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H")  # commit dates are pinned to 2026-01-01
    assert today not in json.dumps(da) and da["identity"]["commit_date"].startswith("2026-01-01T00:00:00")
    assert pathlib.Path(a["markdown"]).read_text().split("## Meta")[0] == pathlib.Path(b["markdown"]).read_text().split("## Meta")[0]


def test_no_stray_file_and_no_lab_name_in_outputs(repo):
    r, shas, _, run = repo
    rc, res, doc = run(shas[1])
    text = pathlib.Path(res["markdown"]).read_text() + json.dumps(doc)
    assert OWNER in text and all(ord(c) < 128 for c in pathlib.Path(res["markdown"]).read_text())


QUESTION = "Is https://github.com/litl/backoff.git interesting as a contribution to my project in the current directory?"


def run_auto(tmp_path, *args, cwd=None):  # CLI --auto under python3 -I in the environment set by the fixture; returns (rc, stdout JSON | text, doc | None)
    out = tmp_path / f"auto{len(list(tmp_path.iterdir()))}"
    p = subprocess.run([sys.executable, "-I", str(TOOLS / "code_capsule.py"), "--auto", "--out", str(out), *args],
                       env=dict(os.environ), capture_output=True, text=True, cwd=cwd or tmp_path)
    res = json.loads(p.stdout) if p.stdout.startswith("{") else p.stdout + p.stderr
    return p.returncode, res, (json.loads(pathlib.Path(res["json"]).read_text()) if p.returncode == 0 else None)


def test_auto_builds_a_marked_capsule_from_the_request(repo, tmp_path):
    r, shas, _, run = repo
    rc, res, doc = run_auto(tmp_path, "--repo", ".", "--question", QUESTION + "\n", "--y-sha", "a" * 40, "--request-date", "2026-10-29", cwd=r)
    assert rc == 0 and res["markdown"].endswith("/capsule.md") and res["json"].endswith("/capsule.json"), res
    assert doc["identity"]["sha"] == shas[1] and res["X"] == f"{r}@{shas[1]}" and res["label"] == "capsule not reviewed"   # HEAD frozen
    assert (doc["intention"], doc["intention_status"]) == (QUESTION, "inferred from the request")                       # word for word
    assert (doc["refusals"], doc["refusals_status"], doc["reviewed_by_owner"]) == ([], "none recorded: implicit authorisation", "no")
    assert (doc["mode"], doc["Y"]["repo"], doc["Y"]["sha"], doc["request_date"]) == ("Y given", "github.com/litl/backoff", "a" * 40, "2026-10-29")
    seams = doc["target_seam"]
    assert 1 <= len(seams) <= 3 and all(s["status"] == "proposed, not reviewed" for s in seams), seams
    assert seams[0]["where"] == f"pkg/__main__.py:1@{shas[1][:12]}" and not any(s["where"].startswith("tests/") for s in seams), seams
    for s in seams:  # every proposed seam exists at the SHA
        assert subprocess.run(["git", "-C", str(r), "cat-file", "-e", f"{shas[1]}:{s['where'].split(':')[0]}"]).returncode == 0, s
    md = pathlib.Path(res["markdown"]).read_text()
    for text in ("capsule not reviewed", "(inferred from the request)", "proposed, not reviewed", "refusals: none recorded: implicit authorisation", QUESTION):
        assert text in md, text
    assert OWNER not in md.split("## Identity")[0] and "evil" not in sys.modules and "pkg" not in sys.modules
    sys.path.insert(0, str(TOOLS))
    import whole_reading                                  # the whole reading finds the proposed seams in capsule.md
    assert [m.group(0) for m in whole_reading.REF.finditer(whole_reading.seam_block(md))] == [s["where"] for s in seams]
    rc, out, _ = run_auto(tmp_path, "--repo", str(r), "--question", QUESTION, "--out", str(pathlib.Path(res["json"]).parent))
    assert (rc, out["refusal"]) == (2, "capsule_exists"), out                        # an existing capsule is never overwritten


def test_auto_finds_x_from_a_subdirectory_and_y_at_head_of_a_bare_repository(repo, tmp_path):
    r, shas, commit, run = repo
    bare = tmp_path / "y.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(r), str(bare)], check=True, capture_output=True)
    head = commit({"later.py": "x = 2\n"})                                           # X moves on; Y stays at the clone
    rc, res, doc = run_auto(tmp_path, "--repo", str(r / "pkg"), "--sha", "HEAD", "--question", QUESTION, "--y-repo", str(bare))
    assert rc == 0 and doc["identity"]["repo"] == str(r) and doc["identity"]["sha"] == head, res
    assert doc["Y"]["sha"] == shas[1] and "bare repository" in doc["Y"]["sha_source"] and res["Y"] == f"github.com/litl/backoff@{shas[1]}"
    rc, res, doc = run_auto(tmp_path, "--repo", str(r), "--question", "What could make my project faster?")
    assert rc == 0 and (doc["mode"], doc["Y"]) == ("need only", "none (need only)") and res["Y"] is None
    rc, res, doc = run_auto(tmp_path, "--repo", str(r), "--question", QUESTION)       # no SHA of Y supplied: unresolved, never invented
    assert doc["Y"]["sha"] is None and "unresolved" in pathlib.Path(res["markdown"]).read_text()


def test_auto_stops_with_capsule_missing_and_a_clear_message(repo, tmp_path):
    r, shas, _, run = repo
    (tmp_path / "plain").mkdir()
    for where in (tmp_path / "plain", tmp_path / "absent"):
        rc, out, _ = run_auto(tmp_path, "--repo", str(where), "--question", QUESTION)
        assert (rc, out["refusal"]) == (2, "capsule_missing") and "give the path of your project" in out["detail"], out
        assert not list(tmp_path.glob("auto*/capsule.*"))
    empty = tmp_path / "empty"
    subprocess.run(["git", "init", "-q", str(empty)], check=True)
    rc, out, _ = run_auto(tmp_path, "--repo", str(empty), "--question", QUESTION)
    assert (rc, out["refusal"]) == (2, "capsule_missing"), out                        # no commit: nothing to pin
    assert run_auto(tmp_path, "--repo", str(r), "--question", "  ")[1]["refusal"] == "question_missing"
    assert run_auto(tmp_path, "--repo", str(r), "--question", QUESTION, "--y", "https://gitlab.com/a/b")[1]["refusal"] == "y_not_github"
    assert run_auto(tmp_path, "--repo", str(r), "--question", QUESTION, "--y-sha", "HEAD")[1]["refusal"] == "sha_format"
    p = subprocess.run([sys.executable, "-I", str(TOOLS / "code_capsule.py"), "--repo", str(r)], capture_output=True, text=True)
    assert p.returncode == 2 and "--sha is required" in p.stderr                     # without --auto the owner path is unchanged


def test_auto_seams_follow_the_module_map_and_skip_tests(repo, tmp_path):
    r, shas, commit, run = repo
    commit({"retrying/__init__.py": "", "retrying/policy.py": "import os\n\n\nclass Policy:\n    pass\n", "retrying/tests/__init__.py": "",
            "docs/conf.py": "def f():\n    pass\n"})
    rc, res, doc = run_auto(tmp_path, "--repo", str(r), "--question", "Can backoff improve the retrying policy of my project?")
    where = [s["where"].split("@")[0] for s in doc["target_seam"]]
    assert where[0] == "retrying/policy.py:4" and len(where) <= 3, where              # module named by the request first, first definition cited
    assert not any(w.startswith(("docs/", "retrying/tests/", "tests/")) for w in where), where


PYPROJECTS = [  # forms met in pyproject.toml files; the minimal parser (Python < 3.11 without tomli) must read them as tomllib does
    FILES_1["pyproject.toml"],
    '[build-system]\nrequires = ["setuptools>=61", \'wheel\']  # comment\nbuild-backend = "setuptools.build_meta"\n\n[project]\nname = "x-y"\n'
    'version = "0.1.0"\ndescription = """Multi\nline "quoted" \\\n    text"""\nreadme = \'README.md\'\nrequires-python = ">=3.9"\n'
    'license = {text = "Apache-2.0"}\nauthors = [{name = "A \\u00e9", email = "a@b"}, { name = "B" }]\nkeywords = []\ndynamic = ["x",]\n'
    'dependencies = [\n  "a>=1",  # why\n  "b[c]; python_version < \'3.11\'",\n]\n[project.optional-dependencies]\ndev = ["pytest"]\n'
    '[project.scripts]\nx-cli = "x.cli:main"\n[project.entry-points."x.plugins"]\none = "x.one:P"\n[tool.black]\nline-length = 88\n'
    'target-version = [\'py39\']\nskip = true\nratio = 1.5e3\nhexa = 0xff\nbig = 1_000\n[[tool.mypy.overrides]]\nmodule = "a.*"\n'
    '[[tool.mypy.overrides]]\nmodule = "b"\nwhen = 2026-10-29\nat = 2026-10-29T10:00:00Z\n[tool.x.y]\nz.w = \'lit\\eral\'\n',
]


def test_minimal_toml_parser_reads_pyproject_like_the_standard_parser():
    cc = module()
    for text in PYPROJECTS:
        got = cc._MiniToml(text).parse()
        assert got["project"]["name"] in ("pkg", "x-y")
        if cc._toml is not None:
            assert got == cc._toml.loads(text) or _dates_as_text(cc._toml.loads(text)) == got, got
    full = cc._MiniToml(PYPROJECTS[1]).parse()["project"]
    assert full["dependencies"] == ["a>=1", "b[c]; python_version < '3.11'"] and full["license"] == {"text": "Apache-2.0"}
    assert full["description"] == 'Multi\nline "quoted" text' and full["authors"][0]["name"] == "A é"
    assert full["entry-points"] == {"x.plugins": {"one": "x.one:P"}} and full["scripts"] == {"x-cli": "x.cli:main"}
    for bad in ('[project]\nname = "trunc', '[project]\ndependencies = [\n  "a",\n', 'a = 1\na = 2\n', 'a = b c\n', '[project\n', 'a = "x\\q"\n',
                'a = {b = 1,}\n', 'd = 1979-05-27 07:32:00Z\n'):
        with pytest.raises(ValueError):
            cc._MiniToml(bad).parse()


def _dates_as_text(d):  # tomllib returns datetime objects where the minimal parser keeps the text
    if isinstance(d, dict):
        return {k: _dates_as_text(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_dates_as_text(v) for v in d]
    return d.isoformat().replace("+00:00", "Z") if hasattr(d, "isoformat") else d


def test_capsule_with_the_minimal_toml_parser_is_the_same_and_says_so(repo):
    r, shas, commit, run = repo
    cc = module()
    saved = cc._toml, cc.TOML_PARSER
    try:
        cc._toml, cc.TOML_PARSER = None, "minimal"
        doc_min, _ = cc.build(str(r), shas[0], None, 50)
    finally:
        cc._toml, cc.TOML_PARSER = saved
    doc_std, _ = cc.build(str(r), shas[0], None, 50)
    assert doc_min["meta"]["toml_parser"] == "minimal" and doc_std["meta"]["toml_parser"] == cc.TOML_PARSER
    assert doc_min["entry_points"]["list"] == doc_std["entry_points"]["list"] and doc_min["license"] == doc_std["license"]
    lim = f"pyproject.toml: {cc.TOML_MINIMAL_LIMIT}"
    assert lim in doc_min["entry_points"]["limits"] and (lim in doc_std["entry_points"]["limits"]) == (cc.TOML_PARSER == "minimal")
    assert [x for x in doc_min["entry_points"]["limits"] if x != lim] == [x for x in doc_std["entry_points"]["limits"] if x != lim]
    assert ("pyproject.toml scripts", "pkg-cli = pkg:main") in {(p["type"], p["text"]) for p in doc_min["entry_points"]["list"]}


if __name__ == "__main__":                               # standard library run; under pytest only the test_* functions are collected
    class _MonkeyPatch:
        """setenv / undo, the part of pytest's monkeypatch these tests use."""
        def __init__(self):
            self.saved = {}

        def setenv(self, k, v):
            self.saved.setdefault(k, os.environ.get(k))
            os.environ[k] = v

        def undo(self):
            for k, v in self.saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    class CodeCapsule(unittest.TestCase):
        """Every test_* function above, each in its own temporary directory (standard library run)."""

    def _method(fn):
        def m(self):
            with tempfile.TemporaryDirectory() as d:
                tmp, mp = pathlib.Path(d), _MonkeyPatch()
                try:
                    made = {}
                    for p in inspect.signature(fn).parameters:
                        made[p] = tmp if p == "tmp_path" else _repo(tmp, mp)
                    fn(**made)
                finally:
                    mp.undo()
        return m

    for _n, _f in list(globals().items()):
        if _n.startswith("test_") and inspect.isfunction(_f):
            setattr(CodeCapsule, _n, _method(_f))

    unittest.main()
