#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Create the Frontier working directory of one idea: frontier-<YYYY-MM-DD>-<short subject>/ (SKILL.md step 0).

Never an existing directory: when the name is taken, -2, -3 ... is appended. Prints the absolute path, which is <dir> for
every later step. Offline, standard library.

Usage: new_run.py "<idea or short subject>" [--parent DIR (default: current directory)] [--date YYYY-MM-DD (default: today)]
Import: slug(text) -> str; create(subject, parent, date) -> Path
"""
import argparse
import datetime
import re
import sys
import unicodedata
from pathlib import Path

MAX_SLUG = 40


def slug(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii').lower()
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    if len(s) > MAX_SLUG:
        cut = s[:MAX_SLUG]
        s = cut.rsplit('-', 1)[0] if '-' in cut else cut
    return s.strip('-') or 'idea'


def create(subject, parent, date):
    parent = Path(parent).resolve()
    base = 'frontier-%s-%s' % (date, slug(subject))
    path, k = parent / base, 1
    while True:
        try:
            path.mkdir(parents=False)
            # round 3: the marker that puts this directory under the R3 rules (guards, checks, complete card); it is also
            # what intake.json frontier_version 3 says, so a host that forgets that field is still held to the rules
            # v2: the same marker with version 4 (a v2 directory is also an R3 directory)
            (path / 'frontier-version.json').write_text('{"frontier_version": 4}\n', encoding='utf-8')
            return path
        except FileExistsError:
            k += 1
            path = parent / ('%s-%d' % (base, k))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('subject')
    ap.add_argument('--parent', default='.')
    ap.add_argument('--date')
    a = ap.parse_args(argv)
    date = a.date or datetime.date.today().isoformat()
    try:
        datetime.date.fromisoformat(date)
    except ValueError:
        print('new_run.py: --date must be YYYY-MM-DD', file=sys.stderr)
        return 2
    if not Path(a.parent).is_dir():
        print('new_run.py: parent directory not found: %s' % a.parent, file=sys.stderr)
        return 2
    print(create(a.subject, a.parent, date))
    return 0


if __name__ == '__main__':
    sys.exit(main())
