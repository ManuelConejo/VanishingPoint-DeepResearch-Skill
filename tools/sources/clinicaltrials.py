# SPDX-License-Identifier: Apache-2.0
"""ClinicalTrials.gov API v2 (keyless): search-clinicaltrials, read nct:NCT<8 digits>."""
import re
import urllib.error, urllib.parse, urllib.request
from sources._common import _before, extra_ok, jget
from sources._common import EXTRA_NO_CHAIN, RELATED_ONLY, value


CTGOV = 'https://clinicaltrials.gov/api/v2/studies'
CT_FIELDS = ('protocolSection.identificationModule,protocolSection.statusModule,protocolSection.conditionsModule,protocolSection.designModule,'
             'protocolSection.sponsorCollaboratorsModule,hasResults')


def ct_item(s, B, with_text=False):
    """ClinicalTrials.gov study. First submitted AND first posted < T. A record updated on/after T: status, phase, enrollment, start date
    and texts are post-T knowledge -> masked; results only when first posted < T; no date on/after T is ever served."""
    ps = s.get('protocolSection') or {}; idm = ps.get('identificationModule') or {}; st = ps.get('statusModule') or {}; de = ps.get('designModule') or {}
    nct = idm.get('nctId'); d = lambda k: (st.get(k) or {}).get('date')
    if not nct or not extra_ok(B, [nct, 'nct:' + nct], [st.get('studyFirstSubmitDate'), d('studyFirstPostDateStruct')], [idm.get('briefTitle'), idm.get('officialTitle')]):
        return None
    fresh = bool(_before(d('lastUpdatePostDateStruct'), B))
    res = _before(d('resultsFirstPostDateStruct'), B)
    keep = (lambda x: x) if fresh else (lambda x: None)
    it = {'id': 'nct:' + nct, 'nct': nct, 'doi': None, 'title': idm.get('briefTitle'), 'year': (d('studyFirstPostDateStruct') or '')[:4],
          'date': d('studyFirstPostDateStruct'), 'date_submitted': st.get('studyFirstSubmitDate'), 'journal': 'ClinicalTrials.gov',
          'sponsor': ((ps.get('sponsorCollaboratorsModule') or {}).get('leadSponsor') or {}).get('name'), 'study_type': de.get('studyType'),
          'conditions': (ps.get('conditionsModule') or {}).get('conditions'), 'status': keep(st.get('overallStatus')), 'phase': keep(de.get('phases')),
          'enrollment': keep((de.get('enrollmentInfo') or {}).get('count')), 'start_date': keep(_before(d('startDateStruct'), B)),   # a planned start on/after T: not served
          'has_results': bool(res and s.get('hasResults', True)), 'date_results_posted': res, 'date_last_update': keep(d('lastUpdatePostDateStruct')),
          'type': 'trial registration', 'validity': 'record unchanged since before T' if fresh else 'record updated on/after T: status, phase, enrollment, start date and texts masked'}
    if with_text:
        ds = ps.get('descriptionModule') or {}; om = ps.get('outcomesModule') or {}
        out = lambda k: [{'measure': o.get('measure'), 'time_frame': o.get('timeFrame')} for o in om.get(k) or []]
        it.update(official_title=idm.get('officialTitle'), abstract=keep(ds.get('briefSummary')) or '(masked: record updated on/after T)',
                  primary_outcomes=keep(out('primaryOutcomes')), secondary_outcomes=keep(out('secondaryOutcomes')),
                  interventions=keep([{'type': i.get('type'), 'name': i.get('name')} for i in (ps.get('armsInterventionsModule') or {}).get('interventions') or []]))
    return it


def search_clinicaltrials(q, n, B):
    """ClinicalTrials.gov API v2 (keyless): first-posted date bounded on the provider side, AREA[StudyFirstPostDate]RANGE[start, eve of T]."""
    lo = B.start.isoformat() if B.since else 'MIN'
    r = jget(CTGOV + '?' + urllib.parse.urlencode({'query.term': q, 'filter.advanced': f'AREA[StudyFirstPostDate]RANGE[{lo},{B.eve}]', 'pageSize': n,
                                                    'countTotal': 'true', 'fields': CT_FIELDS}))
    return [x for x in (ct_item(s, B) for s in r.get('studies', [])) if x], r.get('totalCount')


def read_nct(nct, B):
    if not re.fullmatch(r'NCT\d{8}', nct.upper()): return {'refusal': 'expected form nct:NCT01234567'}
    try: s = jget(CTGOV + '/' + nct.upper())
    except urllib.error.HTTPError as e:
        if e.code == 404: return {'refusal': 'not found'}
        raise
    return ct_item(s, B, with_text=True) or {'refusal': 'after T or forbidden'}


def read_nct_ident(ident, B): return read_nct(value(ident), B)


SOURCE = {
    'name': 'clinicaltrials', 'order': 90,
    'engines': {'clinicaltrials': search_clinicaltrials},
    'ids': [{'prefix': 'nct', 'form': r'NCT\d{8}', 'export': 'trial', 'export_rank': 30}],
    'read': read_nct_ident, 'citing': EXTRA_NO_CHAIN, 'references': EXTRA_NO_CHAIN, 'related': RELATED_ONLY,
    'plugins': ('biology',), 'access': 'api',
    'hosts': {'clinicaltrials.gov': {'interval': 1.0, 'stop': (429,)}},
    'terms': 'ClinicalTrials.gov API v2 (U.S. NLM), keyless',
    'barrier': 'provider side: StudyFirstPostDate in [start, eve of T]; local: first submitted AND first posted dates < T; a record last updated on/after T has its later fields masked',
}
