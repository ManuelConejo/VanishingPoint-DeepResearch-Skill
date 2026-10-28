# SPDX-License-Identifier: Apache-2.0
"""Identification contact VP_CONTACT (KEYS.md, "Identification contact"): not a source and not a secret key, but declared here like
a key so that check_keys / setup_keys list it, install it (~/.config/vp/vp_contact.key, 0600) and announce its absence once.
Resolution: code_sources.contact() (env VP_CONTACT, then the file). An e-mail address unlocks Unpaywall (`email=`) and SEC EDGAR
(declared User-Agent), and identifies VanishingPoint politely to Crossref (polite pool, `mailto=`) and to public pages (User-Agent).
A value without '@' counts as invalid (present() raises ValueError): those engines stay skipped."""
import re
import urllib.error, urllib.parse
import code_sources as sc

FORM = re.compile(r'[^\s<>(),;:@]+@[^\s<>(),;:@]+\.[A-Za-z]{2,}')
FORM_MSG = 'an e-mail address is expected (name@domain.org); a team or project address is best'
PROBE_DOI = '10.1038/nature12373'          # any DOI known to Unpaywall: the check only needs an answer to the e-mail


def present():
    """None when absent; ValueError when set but not an e-mail address; True otherwise. Never the value."""
    c = sc.contact()
    if not c: return None
    if not FORM.fullmatch(c): raise ValueError('VP_CONTACT is not an e-mail address')
    return True


def check_contact(state):
    """Live check (setup_keys.py): one Unpaywall request with the address as email= (Unpaywall answers 422 to an address it refuses)."""
    from sources import unpaywall as u
    try: u.jget(u.API + PROBE_DOI + '?' + urllib.parse.urlencode({'email': u.contact()}))
    except urllib.error.HTTPError as e:
        if e.code == 422: return 'refused'
        raise
    return 'ok'


SOURCE = {
    'name': 'contact', 'order': 1, 'wired': False,
    'key': {'vars': ('VP_CONTACT',), 'send': 'header:User-Agent', 'without': 'degraded', 'engine': 'unpaywall', 'passed': True,
            'hosts': ('api.unpaywall.org', 'efts.sec.gov', 'data.sec.gov', 'www.sec.gov', 'api.crossref.org'),
            'source': 'Contact e-mail (Unpaywall, SEC EDGAR, polite Crossref and public pages)',
            'reason': 'Unpaywall and SEC EDGAR skipped (0 request), Crossref and public pages without a polite identification',
            'free': 'free, no registration; the address is sent to the providers in the User-Agent identification header '
                    '(and as email= to Unpaywall, mailto= to Crossref)',
            'url': 'any e-mail address you are willing to share with the providers, a team or project address is best (KEYS.md, "Identification contact")',
            'prompt': {'VP_CONTACT': 'Your contact e-mail address'}, 'form': (FORM.pattern, FORM_MSG),
            'present': present, 'labels': ['Unpaywall (contact)'], 'check': check_contact,
            'refused': 'address refused by Unpaywall (HTTP 422) — check it is a real e-mail address'},
}
