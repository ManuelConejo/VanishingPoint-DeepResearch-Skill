# SPDX-License-Identifier: Apache-2.0
"""Shared helpers of the data-series sources (dbnomics, fred; plugins/finance.md sections 7-8). Never a source itself.
A value for period P is published, then often revised: "known at T" = periods ending before T AND values as published before T."""
import datetime as dt
import re
from sources._common import CFG, title_sim, tokens


DATA_CFG = CFG['data_series']   # obs_max, dbnomics_datasets (config.json, note)
AS_OF_NOW = 'now (revised values; first releases not available)'
DATA_NO_CHAIN = 'citation chaining not served for data series (dbnomics:, fred:)'


class DataSkip(Exception):
    """A keyed data engine is skipped (credential_missing, key_invalid): a receipt, never "nothing found"."""
    def __init__(self, reason, detail): super().__init__(reason); self.reason, self.detail = reason, detail


def data_forbidden(B, ids, titles):
    """Forbidden identifier or title (same lists as the DOIs and titles of the barrier): counted, True."""
    if any(i and B.is_forbidden(i) for i in ids) or any(t and any(title_sim(tokens(t), f) >= CFG['review_title_threshold'] for f in B.titles) for t in titles):
        B.excluded += 1; return True
    return False


def month_end(y, m): return dt.date(y + m // 12, m % 12 + 1, 1) - dt.timedelta(days=1)


def period_end(p, freq=None):
    """Last day of an observation period, or None (unknown form: refused). DBnomics periods: 2024, 2024-Q3, 2024-S1/H1, 2024-B3 (bimonthly),
    2024-07, 2024-W05, 2024-07-15. FRED dates (period START) with freq A/Q/M/SA/W/BW/D: the end is derived; weekly -> +6 days (conservative)."""
    p = str(p or '').strip()
    try:
        if freq:
            d = dt.date.fromisoformat(p[:10]); f = freq.upper()
            k = {'A': 12, 'SA': 6, 'Q': 3, 'M': 1}.get(f)
            if k: return month_end(d.year, d.month + k - 1)
            return d + dt.timedelta(days={'W': 6, 'BW': 13, 'D': 0}[f]) if f in ('W', 'BW', 'D') else None
        if re.fullmatch(r'\d{4}', p): return dt.date(int(p), 12, 31)
        m = re.fullmatch(r'(\d{4})-([QSHB])(\d)', p)
        if m and 1 <= int(m.group(3)) <= {'Q': 4, 'S': 2, 'H': 2, 'B': 6}[m.group(2)]: return month_end(int(m.group(1)), int(m.group(3)) * {'Q': 3, 'S': 6, 'H': 6, 'B': 2}[m.group(2)])
        m = re.fullmatch(r'(\d{4})-W(\d{2})', p)
        if m: return dt.date.fromisocalendar(int(m.group(1)), int(m.group(2)), 7)
        if re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', p): return month_end(int(p[:4]), int(p[5:]))
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', p): return dt.date.fromisoformat(p)
    except (ValueError, KeyError): return None
    return None


def obs_before_T(rows, B):
    """[(period, value, extra)] -> (kept rows with period end < T and > since, number dropped). Unknown period form = dropped (counted)."""
    keep, drop = [], 0
    for per, val, freq, extra in rows:
        e = period_end(per, freq)
        if e is None or e >= B.T: drop += 1; continue
        if B.since and e.year < B.since: continue
        keep.append(dict({'period': per, 'period_end': e.isoformat(), 'value': None if val in (None, '', '.', 'NA', 'NaN') else val}, **extra))
    B.excluded += drop
    return keep, drop


def obs_cap(keep):
    n = int(DATA_CFG['obs_max'])
    return keep[-n:], (f'last {n} of {len(keep)} observations before T (data_series.obs_max)' if len(keep) > n else None)


def data_engine(search):
    """DataSkip -> skipped receipt (search: (receipt, reason); read: receipt); credential_missing / key_invalid before any request = 0 request."""
    def deco(fn):
        def run(*a, **k):
            try: return fn(*a, **k)
            except DataSkip as e:
                r = {'status': 'skipped', 'reason': e.reason, 'refusal': f'{e.reason}: {e.detail}'}
                return (r, e.reason + ': ' + e.detail) if search else r
        run.__name__ = fn.__name__; run.__doc__ = fn.__doc__
        return run
    return deco
