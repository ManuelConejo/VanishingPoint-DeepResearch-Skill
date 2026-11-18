#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Single input-name tables for local catalogues, directions, saved material and configuration."""
import sys

FIELD_ALIASES = {
    'note': 'relevance', 'annee': 'year', 'titre': 'title', 'methode': 'method', 'capacite': 'capability',
    'entree_sortie': 'input_output', 'resultat': 'result', 'verif': 'verification', 'ampleur': 'scale',
    'donnees': 'data_availability', 'transposable': 'transferability', 'autre_usage': 'other_uses',
    'forme': 'form_score', 'verifiable': 'verifiability', 'liste': 'list', 'sujet': 'subject',
}
EFFORT_ALIASES = {'faible': 'low', 'moyen': 'medium', 'fort': 'high'}
CONFIG_ALIASES = {'tournoi': 'tournament'}
STATE_ALIASES = {'tournoi_rebound.json': 'tournament_rebound.json'}
COLS12 = ['question', 'relevance', 'id', 'year', 'title', 'method', 'capability', 'input_output', 'result',
          'verification', 'scale', 'code']
EXTRA = ['score', 'data_availability', 'transferability', 'other_uses', 'form_score', 'verifiability', 'effort']


def deprecated(old, new):
    print('deprecated name, use %s (%s)' % (new, old), file=sys.stderr)


def normalize_fields(row):
    """Return a copy with English keys; an explicit current key wins."""
    out = dict(row)
    used = []
    for old, new in FIELD_ALIASES.items():
        if old in out:
            out.setdefault(new, out.pop(old))
            used.append((old, new))
    if used:
        deprecated(', '.join(a for a, _ in used), ', '.join(b for _, b in used))
    if 'effort' in out:
        out['effort'] = effort_name(out['effort'])
    return out


def effort_name(value):
    new = EFFORT_ALIASES.get(value, value)
    if new != value:
        deprecated(value, new)
    return new


def read_header(head):
    """Translate a source's available columns, preserving their order and unknown columns.

    Neutral columns belong to either generation. Mixing renamed old and current
    fields is ambiguous even when they do not map to the same column.
    """
    old = [k for k in head if k in FIELD_ALIASES]
    current = [k for k in head if k in FIELD_ALIASES.values()]
    if old and current:
        raise ValueError('mixed old/current table header: use only old or only current field names')
    if old:
        deprecated(', '.join(old), ', '.join(FIELD_ALIASES[k] for k in old))
    return [FIELD_ALIASES.get(k, k) for k in head]


def catalogue_header(head):
    """Accept either complete public layout, never an unknown or mixed layout."""
    reverse = {new: old for old, new in FIELD_ALIASES.items()}
    for columns in (COLS12, COLS12 + EXTRA):
        if head == columns:
            return columns
        if head == [reverse.get(k, k) for k in columns]:
            deprecated('French catalogue header', 'English catalogue header')
            return columns
    raise ValueError('unrecognized catalogue header: expected the complete old or new 12-column or 19-column format')
