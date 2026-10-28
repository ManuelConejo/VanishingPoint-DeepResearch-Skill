# SPDX-License-Identifier: Apache-2.0
"""OpenAIRE Graph: declared, NOT WIRED (no engine yet). Only its optional token is catalogued (check_keys.py, setup_keys.py), so that a
plugin may list OPENAIRE_TOKEN; the token has no effect until a search engine is wired here (CONTRIBUTING.md)."""

SOURCE = {
    'name': 'openaire', 'order': 43, 'wired': False,
    'plugins': ('cs-ai',),
    'key': {'vars': ('OPENAIRE_TOKEN',), 'send': 'bearer', 'hosts': ('api.openaire.eu',), 'without': 'degraded',
            'reason': '60 req/h instead of 7,200', 'free': 'free, account', 'url': 'https://develop.openaire.eu/personal-token',
            'suggest': ('OpenAIRE Graph', '~5 min', True)},
}
