#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline guard of the Python >= 3.9 floor (README): every .py of the skill (tools/, tests/, examples/...) must parse with the Python 3.9
grammar (ast.parse feature_version=(3, 9): no match statement, no parenthesised context managers, no except*, no PEP 695 type syntax...).
feature_version is best effort on recent interpreters: f-strings of the PEP 701 grammar (3.12: same quote nested, backslash or comment
inside a replacement field) are checked from the tokens. A few 3.10+ runtime names the grammar cannot see are refused too: zip(strict=),
itertools.pairwise/batched, hashlib.file_digest, datetime.UTC, an unguarded `import tomllib`, and `X | Y` annotations evaluated at
definition time (no `from __future__ import annotations`)."""
import ast, io, pathlib, sys, tokenize, unittest
ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP = {'.git', '__pycache__', '.pytest_cache'}
NEW_ATTRS = {('itertools', 'pairwise'), ('itertools', 'batched'), ('hashlib', 'file_digest'), ('datetime', 'UTC'), ('dt', 'UTC')}


def sources():
    return sorted(p for p in ROOT.rglob('*.py') if not SKIP & set(p.relative_to(ROOT).parts))


def pep701_issues(src):
    """Positions of f-string constructs older grammars refuse; empty before 3.12 (ast.parse then refuses them itself)."""
    if not hasattr(tokenize, 'FSTRING_START'): return []
    out, stack = [], []   # stack: delimiters of the open f-strings

    def clash(tok):
        body = tok.string.lstrip('rRbBuUfF'); q = body[:3] if body[:3] in ('"""', "'''") else body[:1]
        return any(o == q or (len(o) == 1 and o == q[0]) for o in stack), q
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.FSTRING_START:
            bad, q = clash(tok)
            if bad: out.append((tok.start, 'f-string nested with the same quotes'))
            stack.append(q)
        elif tok.type == tokenize.FSTRING_END: stack.pop()
        elif stack and tok.type == tokenize.STRING:
            if clash(tok)[0]: out.append((tok.start, 'string with the enclosing f-string quotes'))
            if '\\' in tok.string: out.append((tok.start, 'backslash inside an f-string expression'))
        elif len(stack) > 1 and tok.type == tokenize.FSTRING_MIDDLE and '\\' in tok.string: out.append((tok.start, 'backslash inside an f-string expression'))
        elif stack and tok.type == tokenize.COMMENT: out.append((tok.start, 'comment inside an f-string'))
    return out


def modname(v):
    """`itertools` for the name itertools, `datetime` for __import__("datetime"); None otherwise."""
    if isinstance(v, ast.Name): return v.id
    if isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id == '__import__' and v.args and isinstance(v.args[0], ast.Constant):
        return v.args[0].value
    return None


def runtime_issues(tree):
    out, future = [], any(isinstance(n, ast.ImportFrom) and n.module == '__future__' and any(a.name == 'annotations' for a in n.names) for n in tree.body)
    guarded = {id(n) for t in ast.walk(tree) if isinstance(t, ast.Try) for n in ast.walk(t)}
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'zip' and any(k.arg == 'strict' for k in n.keywords):
            out.append((n.lineno, 'zip(strict=) is 3.10+'))
        elif isinstance(n, ast.Attribute) and (modname(n.value), n.attr) in NEW_ATTRS:
            out.append((n.lineno, f'{modname(n.value)}.{n.attr} is 3.10+'))
        elif isinstance(n, ast.ImportFrom) and any((n.module, a.name) in NEW_ATTRS for a in n.names):
            out.append((n.lineno, f'from {n.module} import ... is 3.10+'))
        elif isinstance(n, (ast.Import, ast.ImportFrom)) and id(n) not in guarded and (
                any(a.name == 'tomllib' for a in getattr(n, 'names', [])) and isinstance(n, ast.Import) or getattr(n, 'module', None) == 'tomllib'):
            out.append((n.lineno, 'import tomllib (3.11+) outside a try/except ImportError'))
        elif not future and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            anns = [a.annotation for a in n.args.args + n.args.kwonlyargs + n.args.posonlyargs if a.annotation] + ([n.returns] if n.returns else [])
            out += [(n.lineno, 'X | Y annotation evaluated at definition (3.10+)') for a in anns
                    if any(isinstance(b, ast.BinOp) and isinstance(b.op, ast.BitOr) for b in ast.walk(a))]
    return out


class T(unittest.TestCase):
    def test_sources_found(self):
        names = {p.relative_to(ROOT).as_posix() for p in sources()}
        for f in ('tools/gateway.py', 'tools/code_capsule.py', 'examples/user-sources/local_docs.py', 'tests/test_py39_compat.py'): self.assertIn(f, names)

    def test_grammar_3_9(self):
        bad = []
        for p in sources():
            src = p.read_text(encoding='utf-8')
            try: tree = ast.parse(src, str(p), feature_version=(3, 9))
            except SyntaxError as e: bad.append(f'{p.relative_to(ROOT)}:{e.lineno}: {e.msg}'); continue
            bad += [f'{p.relative_to(ROOT)}:{pos[0]}: {why}' for pos, why in pep701_issues(src)]
            bad += [f'{p.relative_to(ROOT)}:{line}: {why}' for line, why in runtime_issues(tree)]
        self.assertEqual(bad, [], '\n'.join(bad))

    def test_detectors(self):   # the guard itself catches what it claims to catch
        if hasattr(tokenize, 'FSTRING_START'):
            self.assertTrue(pep701_issues('x = f"{", ".join(a)}"\n'))
            self.assertTrue(pep701_issues("x = f'{chr(10)!r}{\"\\n\".join(a)}'\n"))
        self.assertEqual(pep701_issues('x = f"{\', \'.join(a)}"\n'), [])
        self.assertTrue(runtime_issues(ast.parse('zip(a, b, strict=True)')))
        self.assertTrue(runtime_issues(ast.parse('import datetime as dt\ndt.datetime.now(dt.UTC)')))
        self.assertTrue(runtime_issues(ast.parse('__import__("datetime").datetime.now(__import__("datetime").UTC)')))
        self.assertTrue(runtime_issues(ast.parse('import tomllib')))
        self.assertEqual(runtime_issues(ast.parse('try:\n    import tomllib\nexcept ImportError:\n    tomllib = None')), [])
        self.assertTrue(runtime_issues(ast.parse('def f(x: int | None): pass')))
        self.assertEqual(runtime_issues(ast.parse('from __future__ import annotations\ndef f(x: int | None): pass')), [])
        with self.assertRaises(SyntaxError): ast.parse('match x:\n    case 1: pass\n', feature_version=(3, 9))


if __name__ == '__main__':
    unittest.main()
