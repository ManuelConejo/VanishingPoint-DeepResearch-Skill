#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Tests of the general mode of tools/contradictor.py (any plugin but code) without network, real model or cost: a fake Codex
executable for the contradictor (VP_MODEL_COMMAND_OPENAI) and a fake claude executable for the match call and the rereads
(VP_MODEL_COMMAND_CLAUDE). A synthetic biology run holds REPORT.md, card.json, scope.md and sources/<key>/source.txt.
Checked: auto mode picks general (no whole-reading material, no code plugin) and code when scope.md names the code plugin;
the material (sources whole in key order, a source over the cap left out and declared, the bias section of the plugin, T and
the question); the mechanical gates (quotation not found, fragment not verbatim, fragment too short, plugin-only evidence for a
false claim, a miss without source fragment); the match call (not exclusive); the rereads (false detected, false added, miss
verified, miss false); the receipt and the status line; --prompts-only; sources missing; no model name unless given."""
import json, os, pathlib, subprocess, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent.parent / 'tools'
sys.path.insert(0, str(P)); import contradictor as C  # noqa: E402

S1 = ("Record served by the gateway:\nid: pmid:1\n\nVitamin D and respiratory infection: meta-analysis.\n"
      "RESULTS: Supplementation reduced the risk of acute respiratory infection among all participants (adjusted odds ratio 0.88, "
      "95% CI 0.81 to 0.96). Protective effects were seen in those receiving daily or weekly vitamin D without additional bolus doses, "
      "but not in those receiving one or more bolus doses.\n")
S2 = ("Record served by the gateway:\nid: pmid:2\n\nA large trial of monthly vitamin D.\n"
      "RESULTS: Monthly high-dose vitamin D did not reduce acute respiratory infection in older adults (hazard ratio 0.99). "
      "Adherence was lower than planned in the second year.\n")
S3 = "Record served by the gateway:\nid: pmid:3\n\n" + "A very long text. " * 400
REPORT = """# Vitamin D and acute respiratory infection

## Executive Summary
Vitamin D supplementation halves the risk of acute respiratory infection in every regimen [1]. A monthly trial was null [2].

## Introduction
The question as framed.

## Main Analysis
### Finding 1 — Vitamin D lowers the risk
The meta-analysis reports an adjusted odds ratio of 0.88 [1]. The effect was seen with all dosing schedules including bolus doses [1].

### Finding 2 — A null trial
A monthly high-dose trial found no reduction [2]. The trial had lower adherence in the second year [2].

## Synthesis & Insights
Daily dosing looks better.

## Limitations & Caveats
Fewer than ten sources carry the report.

## Recommendations
Watch new trials.

## Bibliography
[1] Meta-analysis, 2017, pmid:1, abstract.
[2] Trial, 2017, pmid:2, abstract.

## Methodology Appendix
Verification: done.
"""
CARD = {"card_id": "t", "question": "What was known at the end of 2020 on vitamin D and acute respiratory infection?",
        "sources": {"S1": {"pmid": "1"}, "S2": {"pmid": "2"}, "S3": {"pmid": "3"}},
        "claims": [{"id": "A1", "text": "aOR 0.88", "source": {"key": "S1"}, "location": "abstract"}], "conclusion": "Modest effect."}
FRAG1 = "but not in those receiving one or more bolus doses"
FRAG2 = "Adherence was lower than planned in the second year"
ANSWER = {"false_claims": [
    {"quote": "The effect was seen with all dosing schedules including bolus doses", "evidence": [{"source": "S1", "fragment": FRAG1}], "why": "really wrong: no effect with bolus"},
    {"quote": "Vitamin D supplementation halves the risk of acute respiratory infection in every regimen", "evidence": [{"source": "S1", "fragment": "reduced the risk by half in all regimens"}], "why": "paraphrased evidence"},
    {"quote": "This sentence is nowhere in the report at all", "evidence": [{"source": "S1", "fragment": FRAG1}], "why": "x"},
    {"quote": "A monthly trial was null", "evidence": [{"source": "S2", "fragment": "x"}], "why": "beyond the cap of three"}],
    "missed": [
    {"angle": "counter-evidence", "claim": "genuinely missing: bolus doses gave no protection", "evidence": [{"source": "[1]", "fragment": FRAG1}, {"source": "plugin:biology", "fragment": "a result on another organism, in vitro, or in silico is indirect evidence"}], "why": "dosing"},
    {"angle": "plugin bias", "claim": "lower adherence in the trial (already stated)", "evidence": ["S2: " + FRAG2], "why": "adherence"},
    {"angle": "plugin bias", "claim": "only a plugin fragment", "evidence": [{"source": "plugin:biology", "fragment": "a result on another organism, in vitro, or in silico is indirect evidence"}], "why": "p"},
    {"angle": "population", "claim": "too short", "evidence": [{"source": "S2", "fragment": "older adults"}], "why": "q"}]}
FAKE_CODEX = r'''#!/usr/bin/env python3
import json, sys
p = sys.stdin.read()
assert sys.argv[-1] == "-" and "exec" in sys.argv, sys.argv
assert "-m" not in sys.argv or sys.argv[sys.argv.index("-m") + 1] != "", sys.argv
assert "# REPORT" in p and "# CARD" in p and "# SOURCES" in p and "=== source S1" in p and "=== plugin:biology" in p
open(sys.argv[0] + ".prompt", "w").write(p)
txt = json.dumps(ANSWER)
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": txt}}))
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 500, "output_tokens": 50}}))
'''.replace('ANSWER)', repr(ANSWER) + ')')
FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, sys
p = sys.stdin.read()
assert "--tools" in sys.argv and sys.argv[sys.argv.index("--tools") + 1] == "", sys.argv
assert "--model" not in sys.argv or sys.argv[sys.argv.index("--model") + 1] != "", sys.argv
if "## List B" in p:
    assert "## List A (sections of the report)" in p and "Fewer than ten sources" in p and "[1] Meta-analysis" not in p
    ids = []
    for chunk in p.split("## List B")[1].split("### ")[1:]:
        bid, body = chunk.split("\n", 1)
        if "already stated" in body: ids.append(bid.strip())
    txt = json.dumps({"pairs": [{"A": "A6", "B": b} for b in ids], "justification": "fake"})
elif "# Quotation from the report" in p:
    assert "# Extracts of the cited sources" in p and "=== S1 (characters 0-" in p
    txt = "CONTRADICTED" if "really wrong" in p else "NOT CONTRADICTED"
else:
    assert "# Research question" in p and "vitamin D" in p
    txt = "FOUND" if "genuinely missing" in p else "ABSENT"
print(json.dumps({"type": "result", "subtype": "success", "result": txt, "total_cost_usd": 0.02, "num_turns": 1, "usage": {}}))
'''


class General(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()); self.run = self.d / 'run'
        for k, t in (('S1', S1), ('S2', S2), ('S3', S3)):
            (self.run / 'sources' / k).mkdir(parents=True); (self.run / 'sources' / k / 'source.txt').write_text(t)
        (self.run / 'REPORT.md').write_text(REPORT); (self.run / 'card.json').write_text(json.dumps(CARD))
        (self.run / 'scope.md').write_text('# Scope\nPlugin: plugins/biology.md\nT = 2021-01-01 (end of 2020)\n')
        for name, src in (('fake-codex', FAKE_CODEX), ('fake-claude', FAKE_CLAUDE)):
            f = self.d / name; f.write_text(src); f.chmod(0o755)
        self.saved = {k: os.environ.get(k) for k in ('VP_MODEL_COMMAND_CLAUDE', 'VP_MODEL_COMMAND_OPENAI', 'VP_HOST', 'VP_MODEL', 'VP_CONTRADICTORS', 'HOME')}
        for k in self.saved: os.environ.pop(k, None)
        os.environ['VP_MODEL_COMMAND_CLAUDE'] = json.dumps([str(self.d / 'fake-claude'), '-p', '--model', '{model}', '--output-format', 'json'])
        os.environ['VP_MODEL_COMMAND_OPENAI'] = json.dumps([str(self.d / 'fake-codex'), 'exec', '-m', '{model}', '--json', '-'])
        os.environ['HOME'] = str(self.d / 'home'); (self.d / 'home').mkdir()

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v

    def tool(self, *args):
        r = subprocess.run([sys.executable, '-I', str(P / 'contradictor.py'), str(self.run), *args], capture_output=True, text=True, env=os.environ, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr); return json.loads(r.stdout.strip().splitlines()[-1])

    def test_prompts_only_material(self):
        s = self.tool('--families', 'openai', '--prompts-only', '--y-cap', '3000')
        self.assertEqual((s['status'], s['mode']), ('prompts', 'general'))
        self.assertEqual((s['sources'], s['sources_included'], s['sources_not_included']), (3, 2, ['S3']))
        self.assertEqual(s['plugins'], ['biology']); self.assertEqual(s['bias_sections'], ['plugin:biology'])
        p = (self.run / 'state' / 'contradictor' / 'PROMPT.md').read_text()
        self.assertIn('T): 2021-01-01', p); self.assertIn(CARD['question'], p); self.assertIn('NOT INCLUDED (contradictor cap): S3', p)
        self.assertLess(p.index('=== source S1'), p.index('=== source S2')); self.assertIn('## Discipline biases', p)
        self.assertNotIn('{', p.split('# REPORT')[0].replace('{"false_claims"', '').replace('{"source"', '').replace('{"angle"', '').replace('{"quote"', ''))

    def test_full_run(self):
        s = self.tool('--families', 'openai')
        self.assertEqual((s['status'], s['mode']), ('done', 'general')); self.assertEqual(s['families']['openai'], 'ok (4 false, 4 missed)')
        rec = json.loads((self.run / 'contradictor.json').read_text()); st = [(e['kind'], e['i'], e['status']) for e in rec['elements']]
        self.assertIn(('false', 1, 'false detected'), st)
        self.assertIn(('false', 2, 'false added: evidence not found verbatim in a source'), st)
        self.assertIn(('false', 3, 'false added: quotation not found in the report'), st)
        self.assertNotIn(4, [i for k, i, _ in st if k == 'false'])
        self.assertIn(('miss', 1, 'miss verified'), st)
        self.assertIn(('miss', 2, 'not exclusive: already stated in the report'), st)
        self.assertIn(('miss', 3, 'miss false: no source fragment (plugin only)'), st)
        self.assertNotIn(4, [i for k, i, _ in st if k == 'miss'])   # at most max_per_list per list
        self.assertEqual(s['false_detected'], 1); self.assertEqual(s['misses_verified'], 1)
        self.assertEqual(rec['misses_verified'][0]['angle'], 'counter-evidence'); self.assertIn('contradicted by <family>', s['note']); self.assertIn('never edits REPORT.md', s['note'])
        self.assertAlmostEqual(rec['cost_usd']['rereads'], 0.06, places=3)   # one match call + two rereads at 0.02
        self.assertEqual(rec['families']['openai']['model'], '(host default)')

    def test_false_with_plugin_evidence_only(self):
        els = C.analyse_general('f', {'false_claims': [{'quote': 'A monthly high-dose trial found no reduction', 'evidence': [{'source': 'plugin:biology', 'fragment': 'Organism and system (`bio.indirectness`)'}], 'why': 'w'}]},
                                REPORT, {'S1': S1, 'plugin:biology': 'x **Organism and system** (`bio.indirectness`): a result'})
        self.assertEqual(els[0]['status'], 'false added: evidence not found verbatim in a source')
        els = C.analyse_general('f', {'false_claims': [{'quote': 'A monthly high-dose trial found no reduction', 'evidence': [{'source': 'plugin:biology', 'fragment': 'Organism and system** (`bio.indirectness`)'}], 'why': 'w'}]},
                                REPORT, {'S1': S1, 'plugin:biology': 'x **Organism and system** (`bio.indirectness`): a result'})
        self.assertEqual(els[0]['status'], 'false added: evidence from the plugin only')

    def test_fragment_normalisation_and_keys(self):
        t = {'S1': 'A  line\nbroken   “quoted” here and more text', 'S12': 'other', 'plugin:law': 'bias text of the law plugin'}
        r = C.check_evidence([{'source': 's1', 'fragment': 'a line broken "quoted" here'}, '[12]: other', {'source': 'S9', 'fragment': 'whatever is long enough'},
                              {'source': 'plugin', 'fragment': 'bias text of the law plugin'}], t)
        self.assertTrue(r[0]['exists']); self.assertEqual(r[1]['note'], 'fragment shorter than 20 characters')
        self.assertEqual(r[2]['note'], 'source not in the material'); self.assertTrue(r[3]['exists']); self.assertEqual(r[3]['side'], 'plugin')

    def test_auto_mode_and_skips(self):
        (self.run / 'scope.md').write_text('Plugin: plugins/code.md\nT = 2021-01-01\n')
        s = self.tool('--families', 'openai'); self.assertEqual(s['status'], 'skipped'); self.assertIn('whole_reading.py', s['note'])
        s = self.tool('--families', 'openai', '--mode', 'general', '--plugin', 'plugins/law.md', '--prompts-only')
        self.assertEqual((s['mode'], s['plugins']), ('general', ['law']))
        (self.run / 'scope.md').write_text('Plugin: law. Mode: standard. Run name: x.\nT = 2021-01-01\n')
        self.assertEqual(C.run_plugins(self.run), ['law'])
        (self.run / 'scope.md').write_text('**Plugins**: cs-ai, finance\n'); self.assertEqual(C.run_plugins(self.run), ['cs-ai', 'finance'])
        (self.run / 'scope.md').write_text('T = 2021-01-01\n')
        for k in ('S1', 'S2', 'S3'): (self.run / 'sources' / k / 'source.txt').unlink()
        s = self.tool('--families', 'openai'); self.assertEqual((s['status'], s['mode']), ('skipped', 'general')); self.assertIn('sources/<key>/source.txt', s['note'])

    def test_absent_without_family(self):
        s = self.tool(); self.assertEqual(s['status'], 'absent')

    def test_two_json_objects(self):
        txt = '{"pairs": [{"A": "A4", "B": "B1"}], "justification": "x"}\n\nCorrection: the pairs above were a mistake.\n{"pairs": [], "justification": "none"}'
        self.assertEqual(C.extract_json(txt), {"pairs": [], "justification": "none"})
        self.assertEqual(C.extract_json('```json\n{"a": 1}\n```'), {"a": 1}); self.assertIsNone(C.extract_json('no json here'))

    def test_report_sections(self):
        items = C.report_sections(REPORT)
        self.assertFalse(any(i.startswith('## Bibliography') for i in items))
        self.assertTrue(any(i.startswith('### Finding 2') for i in items)); self.assertTrue(any(i.startswith('## Limitations') for i in items))
        self.assertFalse(any('### Finding' in i for i in items if i.startswith('## Main Analysis')))


if __name__ == '__main__':
    unittest.main()
