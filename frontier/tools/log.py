#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Append-only decision journal of a Frontier working directory: <dir>/decision_log.jsonl (SKILL.md step 7).

  before  what the researcher WOULD do, written before the result is known (before tools/run_test.py, or before reading
          any outcome); one per test, and never after an "after" of the same test;
  after   what the researcher DOES once the result is known; refused without a "before" of the same test.
Each line: {"utc", "phase", "test", "text", "by"}; "by" = "researcher", or "assumption" (--assumption) when the user was
not there to answer and the agent wrote its own assumption, marked as such. "test" is a test id (T1...) or "idea" for a
decision about the idea as a whole. The file is only ever appended to; a corrupt file is refused, never repaired.
A "before" of a test (T1...) needs <dir>/tests.json holding that test, and freezes its protocol: the line carries
"fingerprint" = SHA-256 of the canonical JSON of the test's predictions, decision rule and simulation parameters
(tools/common.py fingerprint). tools/run_test.py refuses to execute a protocol whose fingerprint differs from the last
"before" of the test, and tools/check.py refuses an executed result whose fingerprint has no earlier "before".

Usage: log.py DIR before|after --test T1 --text "..." [--assumption]
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ written in the skill directory
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import guards  # noqa: E402

LOG = 'decision_log.jsonl'


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def read_entries(path):
    entries = []
    if not path.exists():
        return entries
    for n, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except ValueError:
            raise ValueError('line %d of %s is not JSON; the journal is append-only and is not repaired' % (n, path))
        if not isinstance(e, dict) or e.get('phase') not in ('before', 'after'):
            raise ValueError('line %d of %s is not a journal entry' % (n, path))
        entries.append(e)
    return entries


def executed_test(work):
    try:
        r = common.read_json(Path(work) / 'result.json')
    except (OSError, ValueError):
        return None
    return r.get('test') if isinstance(r, dict) and r.get('mode') == 'executed' else None


def append(work, phase, test, text, assumption=False, observed=None):
    work = Path(work)
    if not work.is_dir():
        raise ValueError('not a directory: %s' % work)
    if phase == 'after' and guards.is_r3(work):
        # round 3 (2.3): an "after" is what the researcher does once a RESULT is known; no result, no "after"
        if assumption:
            raise ValueError('an "after" by assumption would be a decision made up for a result that does not exist: it is a '
                             'scenario; write it in tests.json ranking.scenarios (nothing is logged as "after")')
        if test != executed_test(work) and len((observed or '').strip()) < 20:
            raise ValueError('no executed result for %s: an "after" needs --observed "<the result the researcher actually has, '
                             'at least 20 characters>"; otherwise write a scenario in tests.json ranking.scenarios' % test)
    if not re.fullmatch(r'T[0-9]+|idea', test):
        raise ValueError('--test must be a test id (T1, T2...) or "idea"')
    if not text.strip():
        raise ValueError('--text is empty')
    path = work / LOG
    entries = read_entries(path)
    mine = [e for e in entries if e.get('test') == test]
    if phase == 'after' and not any(e['phase'] == 'before' for e in mine):
        raise ValueError('no "before" entry for %s: write what the researcher would do BEFORE the result first' % test)
    if phase == 'before' and any(e['phase'] == 'after' for e in mine):
        raise ValueError('an "after" entry already exists for %s: a "before" written now would not be a prior' % test)
    fp = None
    if phase == 'before' and test != 'idea':
        try:
            tests = common.read_json(work / 'tests.json')
        except (OSError, ValueError) as e:
            raise ValueError('a "before" of %s freezes its protocol: %s/tests.json is required (%s)' % (test, work, e))
        t = common.find_test(tests, test)
        if t is None:
            raise ValueError('test %s is not in tests.json: write the test before its "before"' % test)
        fp = common.fingerprint(t)
    entry = {'utc': utc_now(), 'phase': phase, 'test': test, 'text': text.strip(),
             'by': 'assumption' if assumption else 'researcher'}
    if fp:
        entry['fingerprint'] = fp
    if phase == 'after' and observed and observed.strip():
        entry['observed'] = observed.strip()
    with open(str(path), 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    return entry


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dir')
    ap.add_argument('phase', choices=['before', 'after'])
    ap.add_argument('--test', required=True)
    ap.add_argument('--text', required=True)
    ap.add_argument('--assumption', action='store_true')
    ap.add_argument('--observed', help='"after" without an executed result (R3 directories): the result the researcher actually has')
    a = ap.parse_args(argv)
    try:
        e = append(a.dir, a.phase, a.test, a.text, a.assumption, a.observed)
    except ValueError as err:
        print('log.py: refused: %s' % err, file=sys.stderr)
        return 1
    print(json.dumps(e, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
