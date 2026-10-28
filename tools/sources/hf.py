# SPDX-License-Identifier: Apache-2.0
"""Hugging Face Hub (keyless): search-hf-models, search-hf-datasets, read hfmodel:<owner/name> | hfdataset:<owner/name>
(card at the last commit of main dated < T)."""
import re
import urllib.error, urllib.parse, urllib.request
from sources._common import _before, fetch, http_code, jget, law_ok
from sources._cs import CS
from sources._common import RELATED_ONLY
from sources._cs import CS_NO_CHAIN, CS_STOP


# ---- Hugging Face Hub (models, datasets). Terms: no clause against automated use; robots "Allow: /"; anonymous 500 req / 5 min / IP.
HF = 'https://huggingface.co/'
HF_KIND = {'hfmodel': 'models', 'hfdataset': 'datasets'}
HF_LEGACY = '2022-03-02'   # Hub migration day: every older repo carries this createdAt (probe 2026-10-28) -> existence attested by a commit dated < T
HF_REPO = r'[A-Za-z0-9][\w.-]{0,95}(/[A-Za-z0-9][\w.-]{0,95})?'


def hf_licence(card, tags):
    l = (card or {}).get('license')
    return l if isinstance(l, str) else next((t[8:] for t in tags or [] if str(t).startswith('license:')), None)


def hf_commit(kind, rid, B):
    """Last commit of main dated < T (newest-first pages of 100, at most cs_engines.hf_commit_pages) -> (commit, newer commits seen) or (None, n)."""
    newer = 0
    for p in range(int(CS.get('hf_commit_pages', 10))):
        page = jget(f'{HF}api/{kind}/{rid}/commits/main?limit=100&p={p}')
        for c in page or []:
            if _before(c.get('date'), B): return c, newer
            newer += 1
        if len(page or []) < 100: break
    return None, newer


def hf_item(r, kind, B, legacy_check=None):
    """Hub repo: created < T (createdAt; a repo of the migration day is attested by a commit dated < T); its id, linked arXiv papers
    (tags arxiv:) checked against the forbidden lists. Downloads and likes are current (as_of "now"); licence, task and tags only when
    lastModified < T (nothing changed since), else masked (read the card at the revision before T). legacy_check: [remaining commit lookups]."""
    rid = r.get('id') or r.get('modelId'); tags = r.get('tags') or []; created = r.get('createdAt'); pre = 'hfmodel' if kind == 'models' else 'hfdataset'
    ids = [rid, f'{pre}:{rid}'] + ['10.48550/arxiv.' + t[6:] for t in tags if str(t).startswith('arxiv:')]
    dates = [created]
    if created and str(created)[:10] == HF_LEGACY and not _before(created, B):
        if not legacy_check or legacy_check[0] <= 0: dates = [None]              # lookup budget spent: not datable -> refused
        else: legacy_check[0] -= 1; c, _ = hf_commit(kind, rid, B); dates = [c.get('date') if c else None]
    if not rid or not law_ok(B, ids, dates, [rid]): return None
    fresh = _before(r.get('lastModified'), B) is not None
    it = {'id': f'{pre}:{rid}', pre: rid, 'title': rid, 'date': str(dates[0])[:10], 'date_created': str(created)[:10] if _before(created, B) else None, 'journal': 'Hugging Face Hub',
          'type': 'model' if kind == 'models' else 'dataset', 'first_author': r.get('author') or rid.split('/')[0],
          'downloads': r.get('downloads'), 'likes': r.get('likes'), 'as_of': 'now', 'url': HF + ('datasets/' if kind == 'datasets' else '') + rid,
          'metadata': 'unchanged since before T (lastModified < T)' if fresh else 'modified on/after T: licence, task and tags masked (read the card at the revision before T)'}
    if fresh:
        it.update(licence=hf_licence(r.get('cardData'), tags), task=r.get('pipeline_tag') or [t[16:] for t in tags if str(t).startswith('task_categories:')] or None,
                  library=r.get('library_name'), arxiv=[t[6:] for t in tags if str(t).startswith('arxiv:')])
    if dates[0] != created: it['date_note'] = 'repository older than the Hub migration (createdAt 2022-03-02): existence dated by its last commit before T'
    return it


def search_hf(kind, q, n, B):
    """Hub search (`search=` on the repo id, most downloaded first; no provider-side date filter): local barrier on createdAt."""
    if not q.strip(): return [], 'empty query'
    rs = jget(f'{HF}api/{kind}?' + urllib.parse.urlencode({'search': q.strip(), 'limit': min(100, 3 * n), 'full': 'true', 'sort': 'downloads', 'direction': -1}))
    out, budget = [], [n]                                                    # at most n commit lookups for repos of the migration day
    for r in rs or []:
        if len(out) >= n: break
        x = hf_item(r, kind, B, budget)
        if x: out.append(x)
    return out, (f'{len(rs or [])} repos returned (search on the repo id, no provider-side date filter: local barrier on createdAt; repos of the 2022-03-02 '
                 f'migration day dated by a commit, {n - budget[0]} lookups); downloads and likes as_of now')


def search_hf_models(q, n, B): return search_hf('models', q, n, B)


def search_hf_datasets(q, n, B): return search_hf('datasets', q, n, B)


def hf_evals(mi):
    """model-index (declared in the card at the revision) -> flat list of self-reported results."""
    out = []
    for m in mi if isinstance(mi, list) else []:
        for r in (m or {}).get('results') or [] if isinstance(m, dict) else []:
            if not isinstance(r, dict): continue
            t, d = r.get('task') or {}, r.get('dataset') or {}
            for x in r.get('metrics') or []:
                if isinstance(x, dict): out.append({'task': t.get('type') or t.get('name'), 'dataset': d.get('name') or d.get('type'), 'config': d.get('config'),
                                                    'split': d.get('split'), 'metric': x.get('name') or x.get('type'), 'value': x.get('value'), 'verified': bool(x.get('verified'))})
    return out[:60]


def read_hf(pre, rid, B):
    """Repo created < T; the card (metadata, model-index, README text) is read at the last commit of main dated < T, never today's."""
    if not re.fullmatch(HF_REPO, rid) or '..' in rid: return {'refusal': f'expected form {pre}:<owner>/<name>, e.g. hfmodel:google-bert/bert-base-uncased'}
    kind = HF_KIND[pre]
    try: info = jget(f'{HF}api/{kind}/{rid}')
    except urllib.error.HTTPError as e:
        if http_code(e) in (401, 403, 404, 410): return {'refusal': f'not found, private or gated (HTTP {http_code(e)})'}
        raise
    c, newer = hf_commit(kind, rid, B)
    if not c: B.excluded += 1; return {'refusal': 'no commit dated before T (repository absent or empty at T)'}
    leg = str(info.get('createdAt'))[:10] == HF_LEGACY and not _before(info.get('createdAt'), B)   # migration day on/after T: the commit < T attests existence
    it = hf_item(dict(info, lastModified=None, createdAt=c.get('date') if leg else info.get('createdAt')), kind, B)
    if not it: return {'refusal': 'after T or forbidden'}
    if leg: it.update(date_created=None, date_note='repository older than the Hub migration (createdAt 2022-03-02): existence dated by its last commit before T')
    sha = c['id']
    try: rev = jget(f'{HF}api/{kind}/{rid}/revision/{sha}')
    except urllib.error.HTTPError as e:
        if http_code(e) not in (401, 403, 404): raise
        rev = {}                                                              # gated: metadata at the revision not readable, nothing else served
    card = rev.get('cardData') if isinstance(rev.get('cardData'), dict) else {}
    try:
        txt = fetch(f"{HF}{'datasets/' if kind == 'datasets' else ''}{rid}/raw/{sha}/README.md").decode('utf-8', 'replace')
        txt = re.sub(r'(?s)\A---\n.*?\n---\n', '', txt).strip()[:6000] or '(empty card)'
    except Exception as e: txt = f'(card text not available at this revision: {str(e)[:60]})'
    it.update(metadata='read at the revision before T', revision=sha, revision_date=str(c.get('date'))[:10], later_commits_masked=newer,
              licence=hf_licence(card, rev.get('tags')), task=card.get('pipeline_tag') or rev.get('pipeline_tag') or card.get('task_categories'),
              library=card.get('library_name') or rev.get('library_name'), datasets=card.get('datasets'), language=card.get('language'),
              eval_results=hf_evals(card.get('model-index') or rev.get('model-index')), eval_note='self-reported in the model card (model-index); verified=true only when the Hub marks it',
              abstract=txt, as_of_note='downloads and likes: observed now (date of the call), not as of T; everything else at the revision before T')
    return it


def read_hf_ident(ident, B):
    p, _, v = ident.partition(':')
    return read_hf(p.lower(), v.strip(), B)


SOURCE = {
    'name': 'hf', 'order': 160,
    'engines': {'hf-models': search_hf_models, 'hf-datasets': search_hf_datasets},
    'ids': [{'prefix': 'hfmodel', 'form': r'[\w.-]+(/[\w.-]+)?', 'export': 'software', 'export_rank': 10},
            {'prefix': 'hfdataset', 'form': r'[\w.-]+(/[\w.-]+)?', 'export': 'dataset', 'export_rank': 80}],
    'read': read_hf_ident, 'citing': CS_NO_CHAIN, 'references': CS_NO_CHAIN, 'related': RELATED_ONLY,
    'plugins': ('cs-ai', 'code'), 'access': 'api',
    'hosts': {'huggingface.co': {'interval': 1.0, 'stop': CS_STOP}},          # 500 req/5 min (documented)
    'terms': 'Hugging Face Hub API, keyless; each repository under its own licence (reported)',
    'barrier': 'no provider-side date filter: local barrier on createdAt (< T); repositories of the 2022-03-02 migration day attested by a commit < T; '
               'the card is read at the last commit of main dated < T',
}
