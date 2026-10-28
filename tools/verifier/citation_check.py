#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Mechanical check of the level-1 verifier's evidence.

Each cited fragment must appear LITERALLY in the text of its source.
Only normalisations: Unicode ligatures/compatibility (NFKC) and whitespace
(all blanks are ignored, which absorbs the erratic spaces of PDFs).
A fragment that cannot be found invalidates the verdict of the claim.

CLI: python3 -I citation_check.py verdicts.json SOURCES_DIR
  (SOURCES_DIR/<KEY>/source.txt; the key is read from the "source" field of the verdict)
Output: JSON list of problems; exit code 1 if there are any.
"""
import json, os, re, sys, unicodedata

PROOF_STATUSES = {"FOUND", "DISTORTED"}
MIN_CHARS = 15  # minimum non-blank characters per fragment


def norm(s):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


def check(verdicts, texts):
    """verdicts: list of dicts; texts: {source_key: normalised text}. Returns {id: [problems]}."""
    problems = {}
    for v in verdicts:
        pb = []
        verdict = (v.get("verdict") or "").upper()
        frags = v.get("fragments") or []
        src = texts.get(v.get("source"))
        if verdict in PROOF_STATUSES:
            if src is None:
                pb.append(f"unknown source key: {v.get('source')!r}")
            elif not frags:
                pb.append("no fragment for a verdict that requires some")
            else:
                for f in frags:
                    nf = norm(f)
                    if len(nf) < MIN_CHARS:
                        pb.append(f"fragment too short: {f!r}")
                    elif nf not in src:
                        pb.append(f"fragment not found: {f[:200]!r}")
        elif verdict not in {"ABSENT", "SOURCE-UNAVAILABLE"}:
            pb.append(f"unknown verdict: {verdict!r}")
        if pb:
            problems[v.get("id")] = pb
    return problems


def load_texts(folder):
    return {key: norm(open(os.path.join(folder, key, "source.txt"), errors="replace").read())
            for key in os.listdir(folder) if os.path.exists(os.path.join(folder, key, "source.txt"))}


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0 if sys.argv[1:2] in (["-h"], ["--help"]) else 2)
    d = json.load(open(sys.argv[1]))
    v = d["verdicts"] if "verdicts" in d else [dict(x, verdict={"INVALID": "DISTORTED", "UNVERIFIED": "SOURCE-UNAVAILABLE"}.get(x.get("status"), x.get("status")),
                                                     source=re.sub(r"[^\w.-]+", "_", str(x.get("source") or "")).strip(".") or "source")
                                               for x in d.get("claims", [])]   # verifier.py verify writes "claims" (status, card key)
    p = check(v, load_texts(sys.argv[2]))
    print(json.dumps(p, ensure_ascii=False, indent=1))
    sys.exit(1 if p else 0)
