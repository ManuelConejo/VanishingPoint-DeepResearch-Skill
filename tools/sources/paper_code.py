# SPDX-License-Identifier: Apache-2.0
"""Code of a paper (code engine `paper-code`, plugins/code.md, cs-ai.md): paper-code <arXiv id> -> repositories, models, datasets and
spaces linked on Hugging Face Papers. Client: code_sources.CodeClient."""
import code_sources as sc


def run_paper_code(g, arg, n, opt, B, extra):
    return sc.PaperCode(g.client).search(arg, limit=n)


SOURCE = {
    'name': 'paper-code', 'order': 46,
    'commands': {'paper-code': {'engine': 'paper-code', 'run': run_paper_code}},
    'serves': ('hf-papers',),
    'plugins': ('code', 'cs-ai'), 'access': 'api',
    'hosts': {'huggingface.co': {}},
    'terms': 'Hugging Face Papers API, keyless',
    'barrier': 'every dated item (repository, model, dataset, space) >= T removed; undated items kept with dating "absent" (Gateway._date_filter)',
}
