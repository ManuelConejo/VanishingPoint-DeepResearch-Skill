# SPDX-License-Identifier: Apache-2.0
"""Code of a paper (code engine `paper-code`, plugins/code.md, cs-ai.md): paper-code <arXiv id> -> repositories, models, datasets and
spaces linked on Hugging Face Papers, dated as code_sources.PaperCode says (githubRepo on GitHub, models by creation).
Client: code_sources.CodeClient."""
import code_sources as sc


def run_paper_code(g, arg, n, opt, B, extra):
    return sc.PaperCode(g.client, extra).search(arg, limit=n, B=B)


SOURCE = {
    'name': 'paper-code', 'order': 46,
    'commands': {'paper-code': {'engine': 'paper-code', 'run': run_paper_code}},
    'serves': ('hf-papers',),
    'plugins': ('code', 'cs-ai'), 'access': 'api',
    'hosts': {'huggingface.co': {}, sc.GH_API_HOST: {}, sc.GH_RAW_HOST: {}},
    'terms': 'Hugging Face Papers API, keyless',
    'barrier': 'the paper dated by the earlier of its arXiv identifier month and HF publishedAt; githubRepo dated on GitHub (repo-head barrier: created '
               'before T, last commit before T, its SHA served), refused otherwise; models and datasets dated by creation (search-hf-models rules); '
               'every dated item >= T removed; undated items kept with dating "absent" (Gateway._date_filter)',
}
