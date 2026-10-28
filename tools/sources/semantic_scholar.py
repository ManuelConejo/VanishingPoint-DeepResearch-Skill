# SPDX-License-Identifier: Apache-2.0
"""Semantic Scholar: declared, NOT WIRED (no engine yet). Only its optional key is catalogued (check_keys.py, setup_keys.py), so that a
plugin may list S2_API_KEY; the key has no effect until a search engine is wired here (CONTRIBUTING.md)."""

SOURCE = {
    'name': 'semantic-scholar', 'order': 42, 'wired': False,
    'plugins': ('cs-ai',),
    'key': {'vars': ('S2_API_KEY',), 'send': 'header:x-api-key', 'hosts': ('api.semanticscholar.org',), 'without': 'skipped',
            'reason': 'search only with a key (429 without)', 'free': 'free by form, CC BY-NC, no redistribution',
            'url': 'https://www.semanticscholar.org/product/api#api-key-form',
            'suggest': ('Semantic Scholar', 'form, key sent by e-mail; data CC BY-NC, attribution', True)},
}
