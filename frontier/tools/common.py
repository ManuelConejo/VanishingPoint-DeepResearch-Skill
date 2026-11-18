#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Shared helpers of the Frontier tools (no command line). Standard library only, offline.

  config()                     frontier/config.json, with the environment overrides:
                               FRONTIER_HOST_FAMILY -> critic.host_family; FRONTIER_CRITIC_FAMILIES (comma list) ->
                               critic.families; FRONTIER_SEARCH_MODEL -> search_model. No family or model is written in
                               the code: they come from the configuration or the environment only.
  family(name, cfg)            normalised family name (lower case, aliases of config.json critic.aliases applied).
  fingerprint(test)            SHA-256 (hex) of the canonical JSON of {"predictions", "decision_rule",
                               "simulation_parameters"} of one test of tests.json (regression specification R37); canonical = keys sorted,
                               separators "," and ":", UTF-8, non-ASCII kept.
  simulation_parameters(sens)  the parameters of sensitivity.simulation (design, n, sd, base, alpha, reps, seed,
                               threshold, rule, scenarios [{name, effect, expected}]), or {"not_applicable": reason}.
  config()["rebound"]          thresholds of the rebound step (steps 8 and 8-bis), defaults DEFAULT_REBOUND.
  config()["history"]          limits of the "Already tried here" step (tools/history.py), defaults DEFAULT_HISTORY.
  config()["context"], ["matter"], ["moment"]   limits of tools/context.py, matter.py, and the thresholds of the moment
                               reading (defaults DEFAULT_CONTEXT, DEFAULT_MATTER, DEFAULT_MOMENT).
  config()["tree_dir"], ["catalogue"], ["directions_index"]   folder of IDEA-TREE.json and the two OPTIONAL local sources;
                               environment FRONTIER_TREE_DIR, FRONTIER_CATALOGUE, FRONTIER_DIRECTIONS_INDEX replace them;
                               None when not configured.
  fold(s), words(s), term_pattern(term), norm_ws(s)   accent- and case-free matching shared by history.py and check.py.
  is_placeholder(s, min_len)   True for an empty filling ("n/a", "none", "tbd", "-", ...) or a string shorter than min_len.
  atomic_write(path, text)     write a temporary file in the same directory, then rename it over path.
  sha256_file(path)            hex digest of the bytes of a file.
"""
import hashlib
import json
import os
import re
import sys
import tempfile
import unicodedata
from pathlib import Path

# Loaded by all local table readers, including check.py.
import input_names

FRONTIER = Path(__file__).resolve().parent.parent
SIM_KEYS = ('design', 'n', 'sd', 'base', 'alpha', 'reps', 'seed', 'threshold', 'rule')
PLACEHOLDERS = {'n/a', 'na', 'n.a', 'none', 'not applicable', 'tbd', 'tbc', 'todo', '-', '--', '---', '...', '…',
                'null', 'nil', 'nothing', 'unknown', 'same', 'idem', 'see above', 'as above', '?', 'x', 'xx', 'xxx'}
DEFAULT_LIMITS = {'memory': '2g', 'cpus': '2', 'pids_limit': 256, 'user': '65534:65534', 'output_cap_bytes': 1000000}
DEFAULT_BUDGET = {'vp_runs': 3, 'critiques': 1, 'executions': 1}
DEFAULT_REBOUND = {'ideas_min': 5, 'ideas_max': 10, 'after_min': 2, 'after_max': 4, 'max_per_operator': 2,
                   'max_retained': 2, 'duplicate_overlap': 0.6, 'prior_art_checks_max': 10, 'prior_art_checks_card_max': 14}


DEFAULT_HISTORY = {
    'max_files': 5000, 'max_file_bytes': 1000000, 'max_total_bytes': 50000000, 'max_entries_per_file': 40,
    'max_excerpt_chars': 160, 'max_condition_chars': 300, 'window_lines': 3, 'file_verdict_lines': 80, 'title_lines': 5,
    'max_block_lines': 30, 'leak_shingle_words': 5,
    'ignore_dirs': ['.git', '.hg', '.svn', 'venv', '.venv', 'node_modules', '__pycache__', '.tox', '.mypy_cache',
                    '.pytest_cache', 'site-packages'],
    'extensions': ['md', 'txt', 'rst', 'py', 'json', 'yaml', 'yml'],
}


DEFAULT_CONTEXT = {'max_files': 200, 'max_file_bytes': 1000000, 'max_candidates': 60, 'max_excerpt_chars': 160}
DEFAULT_MATTER = {'code_plugin': 'code', 'literature_plugin': 'cs-ai', 'min_overlap': 2, 'max_candidates': 10,
                  'timeout_s': 120}
DEFAULT_MOMENT = {'rise': 0.25, 'revive_factor': 2.0, 'trough_ratio': 0.5, 'min_total': 30}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def fold(s):
    """Lower-case and accent-free copy of s, character for character (same length: positions stay valid)."""
    out = []
    for ch in str(s):
        base = ''.join(c for c in unicodedata.normalize('NFKD', ch) if not unicodedata.combining(c)).lower()
        out.append(base if len(base) == 1 else (ch.lower()[:1] or ch))
    return ''.join(out)


def words(s):
    """Folded alphanumeric words of s."""
    return re.findall(r'[a-z0-9]+', fold(s))


def term_pattern(term):
    """Compiled regex (to run on fold(text)) that finds `term` as whole words: accents and case ignored, any short
    separator between its words, an optional plural s. None when the term has no word."""
    parts = re.findall(r'[a-z0-9]+', fold(term))
    if not parts:
        return None
    return re.compile(r'(?<![a-z0-9])' + r'[^a-z0-9]{1,3}'.join(re.escape(p) for p in parts) + r'(?:s|x)?(?![a-z0-9])')


def norm_ws(s):
    return re.sub(r'\s+', ' ', fold(s)).strip()


def config():
    try:
        cfg = read_json(FRONTIER / 'config.json')
    except (OSError, ValueError):
        cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    for old, new in input_names.CONFIG_ALIASES.items():
        if old in cfg:
            input_names.deprecated(old, new)
            if new not in cfg:
                cfg[new] = cfg[old]
            else:
                print('configuration: %s ignored because %s is present' % (old, new), file=sys.stderr)
            del cfg[old]
    cfg.setdefault('rebound_vp_max_calls_per_neighbour', 15)
    cfg.setdefault('power_min_threshold', 0.8)
    critic = dict(cfg.get('critic') or {})
    critic.setdefault('host_family', None)
    critic.setdefault('families', [])
    critic.setdefault('aliases', {})
    env = os.environ
    if env.get('FRONTIER_EXECUTION_ENABLED', '').strip() == '1':   # explicit opt-in by the user, like editing config.json
        cfg['execution_enabled'] = True
    if env.get('FRONTIER_HOST_FAMILY', '').strip():
        critic['host_family'] = env['FRONTIER_HOST_FAMILY'].strip()
    if env.get('FRONTIER_CRITIC_FAMILIES', '').strip():
        critic['families'] = [f.strip() for f in env['FRONTIER_CRITIC_FAMILIES'].split(',') if f.strip()]
    cfg['critic'] = critic
    if env.get('FRONTIER_SEARCH_MODEL', '').strip():
        cfg['search_model'] = env['FRONTIER_SEARCH_MODEL'].strip()
    limits = dict(DEFAULT_LIMITS)
    limits.update(cfg.get('run_limits') or {})
    cfg['run_limits'] = limits
    budget = dict(DEFAULT_BUDGET)
    budget.update(cfg.get('budget') or {})
    cfg['budget'] = budget
    if not isinstance(cfg.get('second_critiques_max'), int) or isinstance(cfg.get('second_critiques_max'), bool):
        cfg['second_critiques_max'] = 1             # round 3: one second critique (on the corrections) per idea
    rebound = dict(DEFAULT_REBOUND)
    rebound.update(cfg.get('rebound') or {})
    cfg['rebound'] = rebound
    history = dict(DEFAULT_HISTORY)
    history.update(cfg.get('history') or {})
    cfg['history'] = history
    for key, default in (('context', DEFAULT_CONTEXT), ('matter', DEFAULT_MATTER), ('moment', DEFAULT_MOMENT)):
        merged = dict(default)
        merged.update(cfg.get(key) or {})
        cfg[key] = merged
    # optional local sources and the folder of the idea tree: a path in config.json, replaced by the environment
    for key, var in (('tree_dir', 'FRONTIER_TREE_DIR'), ('catalogue', 'FRONTIER_CATALOGUE'),
                     ('directions_index', 'FRONTIER_DIRECTIONS_INDEX')):
        cfg.setdefault(key, None)
        if env.get(var, '').strip():
            cfg[key] = env[var].strip()
        elif not isinstance(cfg[key], str) or not cfg[key].strip():
            cfg[key] = None
    return cfg


def family(name, cfg=None):
    n = re.sub(r'\s+', ' ', name.strip().lower()) if isinstance(name, str) else ''
    aliases = {str(k).lower(): str(v).lower() for k, v in ((cfg or config())['critic'].get('aliases') or {}).items()}
    return aliases.get(n, n)


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def simulation_parameters(sens):
    sens = sens if isinstance(sens, dict) else {}
    sim = sens.get('simulation')
    if isinstance(sim, dict):
        params = {k: sim.get(k) for k in SIM_KEYS}
        params['scenarios'] = [{'name': s.get('name'), 'effect': s.get('effect'), 'expected': s.get('expected')}
                               for s in (sim.get('scenarios') or []) if isinstance(s, dict)]
        return params
    return {'not_applicable': sens.get('simulation_not_applicable')}


def fingerprint(test):
    obj = {'predictions': test.get('predictions'), 'decision_rule': test.get('decision_rule'),
           'simulation_parameters': simulation_parameters(test.get('sensitivity'))}
    return hashlib.sha256(canonical(obj).encode('utf-8')).hexdigest()


def find_test(tests_json, test_id):
    if not isinstance(tests_json, dict):
        return None
    for t in tests_json.get('tests') or []:
        if isinstance(t, dict) and t.get('id') == test_id:
            return t
    return None


def read_tsv(path):
    """Rows (dicts keyed by the header line) of a tab-separated file; empty lines and lines starting with # are skipped,
    a short row is padded and an overlong row truncated, as in the original reader.
    Source columns may be partial, reordered or extended; only mixed old/current
    field names are refused. Full catalogue validation belongs to ingest/check."""
    lines = Path(path).read_text(encoding='utf-8', errors='replace').replace('\r\n', '\n').split('\n')
    lines = [l for l in lines if l.strip() and not l.startswith('#')]
    if not lines:
        return []
    head = [h.strip() for h in lines[0].split('\t')]
    head = input_names.read_header(head)
    rows = []
    for l in lines[1:]:
        cells = l.split('\t')
        cells += [''] * (len(head) - len(cells))
        rows.append(input_names.normalize_fields(dict(zip(head, cells[:len(head)]))))
    return rows


ROLE_NAMES = {'n': ('n_periods', 'n_units', 'n', 'effectif', 'headcount', 'n_obs', 'n_pairs', 'n_per_arm',
                    # v2: names the extraction of a project often finds
                    'n_quarters', 'n_months', 'n_years', 'n_rebalances', 'n_observations', 'n_samples'),
              'sd': ('sd', 'std', 'stdev', 'noise_sd'), 'base': ('base', 'base_rate')}


def context_inputs(intake):
    """The key numbers of intake.json context that tools/sim.py may use, as {role: {name, value, cited, source}} for the
    roles n, sd and base. Only a usable number counts: confirmed, or given by the user and not marked unconfirmed. A number
    with an explicit role keeps it; one without a role is matched by its usual name (ROLE_NAMES)."""
    ctx = intake.get('context') if isinstance(intake, dict) else None
    kns = [k for k in (ctx.get('key_numbers') if isinstance(ctx, dict) else None) or [] if isinstance(k, dict)]
    usable = [k for k in kns if isinstance(k.get('value'), (int, float)) and not isinstance(k.get('value'), bool)
              and (k.get('confirmed') is True or (k.get('source') == 'user' and k.get('confirmed') is not False))]
    out = {}
    for role in ROLE_NAMES:
        pick = next((k for k in usable if k.get('role') == role), None)
        if pick is None:
            pick = next((k for k in usable if not k.get('role') and fold(k.get('name', '')) in ROLE_NAMES[role]), None)
        if pick is not None:
            out[role] = {'name': pick.get('name'), 'value': pick.get('value'), 'cited': pick.get('cited'),
                         'source': pick.get('source')}
    return out


def is_placeholder(s, min_len=20):
    if not isinstance(s, str):
        return True
    t = re.sub(r'\s+', ' ', s.strip().lower()).rstrip('.').strip()
    return t in PLACEHOLDERS or len(s.strip()) < min_len


def atomic_write(path, text):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json(path, data):
    atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False) + '\n')


def sha256_file(path):
    h = hashlib.sha256()
    with open(str(path), 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()
