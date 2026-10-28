# Scope — run an13 (T = 2026-08-26, standard mode, plugin cs-ai)

Question: critical analysis of on-policy self-distillation for LLMs where the teacher = the same model conditioned on privileged information (PI) unavailable at test time (e.g. ground-truth solution, reference answer, hint, feedback); how the asymmetry creates a learning signal and a bias, notably progressive collapse of diversity of reasoning paths; three levers (token weighting, nature of PI, teacher dynamics with guidance decay); established vs disputed, in mathematical reasoning.

## Criteria
- Object: LLMs (reasoning/math), self-distillation, teacher = student with privileged context (solution, answer, hints, feedback, demonstrations), on-policy (student samples, teacher scores tokens: reverse KL / per-token advantage).
- Mechanism: on-policy distillation (OPD), self-distillation (OPSD, SDPO, "self-distilled reasoner", context distillation, hindsight/privileged-information teacher, RL with rich feedback), token-level reward/weighting, entropy/diversity collapse, pass@k, EMA/frozen teacher, guidance decay/annealing.
- Comparators: GRPO/RLVR, SFT, off-policy distillation, external teacher OPD.
- Outcomes: accuracy (AIME, MATH, GSM8K...), pass@k, entropy, response length, diversity of reasoning paths, stability.
- Types: arXiv preprints, proceedings, OpenReview; 2023 – T. Language: English.
- Off topic: vision, speech, pure RL theory without LLM, non-math only (kept as context).
- Viewpoints: proponents of OPSD/SDPO, critics (collapse, leakage, shortcut, teacher-student gap), analyses of RLVR diversity (pass@k), theory of privileged information (LUPI).
- Assumptions: reader technical; "guidance decay" = annealing of teacher PI/teacher weight over training. Terms may be recent (2025-2026); if sources are missing say so.

## Angles
1. Core: on-policy self-distillation with privileged information (OPSD, self-distillation policy optimization, SDPO, "self-distillation" reasoning) — arxiv, openalex.
2. On-policy distillation foundations (GKD, reverse KL, on-policy distillation, Thinking Machines style), mode-seeking, exposure bias.
3. Diversity / entropy collapse in RLVR and distillation; pass@k; reasoning-path diversity; token-level entropy.
4. Token weighting: token-level credit, high-entropy forking tokens, per-token advantage, KL weights, clipping.
5. Nature of privileged information: ground-truth solution, answer only, hints, rationalization (STaR), hindsight, feedback; leakage/shortcut; teacher-student gap; LUPI.
6. Teacher dynamics: frozen vs EMA vs current policy teacher, guidance decay/annealing, curriculum of hints, self-reinforcement/model collapse.
7. Critiques/limits/negative results: collapse, answer-leak, contamination, single-seed, scale of models; replications.
8. Neighbouring: context distillation, prompt distillation, hint-based RL (e.g. guided RL, BREAD, StepHint, LUFFY), rich-feedback RL.

## Order
Angle 1,2 first (define), then 3-6 mechanisms, 7 critiques.

## Budget
cap 60 calls total; verifier reserved ~15; first wave <= 27 calls (4 searchers ~7 each); complements ~10.

## Provisional plan of findings
1. Mechanism: privileged-teacher OPD gives dense token-level signal.
2. Asymmetry bias: teacher sees answer -> confident, narrows; diversity collapse evidence.
3. Lever 1: token weighting.
4. Lever 2: nature of PI.
5. Lever 3: teacher dynamics and guidance decay.
6. Established vs disputed.

## Waves
