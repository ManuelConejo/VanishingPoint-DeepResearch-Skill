#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Temporary public-path transition; remove in a later release."""
import os, pathlib, sys

if __name__ == '__main__':
    print('deprecated path, use frontier/tools/tournament.py', file=sys.stderr, flush=True)
    os.execv(sys.executable, [sys.executable, '-I', str(pathlib.Path(__file__).with_name('tournament.py')), *sys.argv[1:]])
