# SPDX-License-Identifier: Apache-2.0
"""Public input aliases. Outputs always use the current name."""
import sys

ENGINE_ALIASES = {'justice-administrative': 'administrative-justice'}
CONFIG_ALIASES = {'possibles': 'candidate_reading'}
READING_ALIASES = {'possibles': 'candidate_reading', 'read_possibles': 'read_candidates'}


def deprecated(old, new):
    print('deprecated name, use %s (%s)' % (new, old), file=sys.stderr)


def engine_name(name):
    if not isinstance(name, str):
        return name
    new = ENGINE_ALIASES.get(name, name)
    if new != name:
        deprecated(name, new)
    return new


def command_name(name):
    if isinstance(name, str) and name.startswith('search-') and name[7:] in ENGINE_ALIASES:
        new = 'search-' + ENGINE_ALIASES[name[7:]]
        deprecated(name, new)
        return new
    return name
