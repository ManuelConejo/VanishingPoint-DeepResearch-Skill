# Cited Passages

Each passage below is copied by tools/passages.py from the source text the verifier read; it is an exact substring of that text (whitespace collapsed), never written by a model. A claim without one says why.
Claims with a verified passage: 29 of 29.

## [1]

- A1 (FOUND, source S1; 2601.18734, full text v3 (2026-03-20))
  Claim (card): ` OPSD trains a model on its own rollouts with a teacher that is the same model given privileged information such as a verified solution, while the student sees only the question `

  ```text
  Inspired by the intuition that a sufficiently capable LLM can rationalize external privileged reasoning traces and teach its weaker self, we introduce \emph{On-Policy Self-Distillation} (OPSD), a learning algorithm where a single LLM acts as both teacher and student with different contexts.
  ```

  ```text
  The teacher policy conditions on privileged information (e.g., verified reasoning traces) while the student policy sees only the question; training minimizes the per-token divergence between these distributions over the student's own rollouts.
  ```

- A2 (DISTORTED, source S1; 2601.18734, full text v3 (2026-03-20))
  Claim (card): ` OPSD is reported as 4-8x more token-efficient than GRPO on mathematical reasoning benchmarks `

  ```text
  We demonstrate the efficacy of our method on multiple mathematical reasoning benchmarks, achieving superior token efficiency compared to reinforcement learning methods and better performance over off-policy distillation methods.
  ```

  ```text
  \item We evaluate OPSD on three competition-level mathematical reasoning tasks, demonstrating that it matches the performance of GRPO with significantly improved token efficiency and outperform supervised fine-tuning.
  ```

  ```text
  each problem requiring only 1024 sampled tokens, whereas GRPO requires 8 rollouts of 16k tokens each
  ```

- A22 (DISTORTED, source S1; 2601.18734, full text v3 (2026-03-20))
  Claim (card): ` Finding 1 verdict: the OPSD recipe trains and is token-efficient in the authors' settings (4-8x over GRPO, one team); independent replication is open `

  ```text
  We demonstrate the efficacy of our method on multiple mathematical reasoning benchmarks, achieving superior token efficiency compared to reinforcement learning methods and better performance over off-policy distillation methods.
  ```

  ```text
  \item We evaluate OPSD on three competition-level mathematical reasoning tasks, demonstrating that it matches the performance of GRPO with significantly improved token efficiency and outperform supervised fine-tuning.
  ```

  ```text
  As shown in ~\cref{fig:token_efficiency}, \ours{} achieves higher token learning efficiency within 100 steps of training as compared to GRPO.
  ```

## [2]

- A3 (FOUND, source S2; 2603.24472, full text v4 (2026-08-18))
  Claim (card): ` A rich-context teacher suppresses expression of uncertainty and shortens responses, degrading math performance by up to 40 % in Qwen3-8B, DeepSeek-Distill-Qwen-7B and Olmo3-7B-Instruct `

  ```text
  Across Qwen3-1.7B/8B, DeepSeek-Distill-Qwen-7B, and Olmo3-7B-Instruct, we observe performance drops of up to 40\%.
  ```

  ```text
  conditioning the teacher on rich information suppresses uncertainty expression, enabling rapid in-domain optimization with limited task coverage but harming OOD performance
  ```

  ```text
  However, in mathematical reasoning, we find that it can reduce response length while degrading performance.
  ```

- A30 (DISTORTED, source S2; 2603.24472, full text v4 (2026-08-18))
  Claim (card): ` Finding 4: rich-context teachers suppress uncertainty, so the richest context can be harmful `

  ```text
  \textbf{Takeaway 4}}: Epistemic Verbalization Depends on Task Generalization
  ```

  ```text
  The value of epistemic verbalization scales with generalization demands: largely redundant for familiar, repetitive tasks (small $|\mathcal{D}|$) and removable for efficiency, but increasingly important as task diversity grows.
  ```

## [3]

- A6 (FOUND, source S3; 2606.26091, full text v1 (2026-06-24))
  Claim (card): ` On-policy self-distillation with sampled demonstrations shows decreasing rollout diversity and flattening pass@k, on graph path-finding and science QA, not mathematics `

  ```text
  We show that this could come at a hidden cost: rollout diversity decreases and pass@k curves flatten (i.e., generating more rollouts fails to improve accuracy).
  ```

  ```text
  On a controlled graph path-finding task and science question-answering benchmarks, self-distilled models match or exceed RL on average performance
  ```

- A24 (FOUND, source S3; 2606.26091, full text v1 (2026-06-24))
  Claim (card): ` Finding 2: the only direct diversity-collapse measurement (falling rollout diversity, flattening pass@k) is on graph path-finding and science QA, not math `

  ```text
  We show that this could come at a hidden cost: rollout diversity decreases and pass@k curves flatten (i.e., generating more rollouts fails to improve accuracy).
  ```

  ```text
  On a controlled graph path-finding task and science question-answering benchmarks, self-distilled models match or exceed RL on average performance
  ```

## [4]

- A4 (FOUND, source S4; 2605.11609, full text v1 (2026-05-12))
  Claim (card): ` PI inflates teacher confidence on solution-implied tokens and deflates it on deliberation tokens such as Wait, Let, Maybe `

  ```text
  it inflates the teacher's confidence on tokens already implied by the solution (structural connectives, verifiable claims) and deflates it on deliberation tokens
  ```

- A8 (FOUND, source S4; 2605.11609, full text v1 (2026-05-12))
  Claim (card): ` An entropy gate switches off the PMI term once teacher entropy collapses, across five models from 4B to 30B, with up to 11.5 points over GRPO and 2 to 10x fewer training steps `

  ```text
  An entropy-triggered gate disables the term once the teacher entropy collapses, completing a drop-in replacement for default self-distillation.
  ```

  ```text
  Across five models from 4B to 30B parameters on math reasoning benchmarks, AntiSD reaches the GRPO baseline's accuracy in $2$ to $10\times$ fewer training steps and improves final accuracy by up to $11.5$ points.
  ```

## [5]

- A5 (FOUND, source S5; 2605.18529, full text v1 (2026-05-18))
  Claim (card): ` Raw oracle solutions are linked to over-conditioned teacher distributions, implicit answer leakage and late-stage training collapse `

  ```text
  While on-policy self-distillation attempts to resolve this by conditioning a self-teacher on privileged contexts, direct exposure to raw oracle solutions often induces over-conditioned teacher distributions, implicit answer leakage, and late-stage training collapse.
  ```

- A16 (FOUND, source S5; 2605.18529, full text v1 (2026-05-18))
  Claim (card): ` Temporal annealing is part of AMR-SD, which names late-stage training collapse as the failure it addresses `

  ```text
  Combined with temporal annealing, this mechanism preserves the base environmental reward while filtering out distributional noise.
  ```

  ```text
  Experiments across scientific, mathematical, and tool-use benchmarks demonstrate that AMR-SD significantly outperforms existing baselines, achieving robust long-horizon stability and successfully preventing late-stage collapse.
  ```

## [6]

- A7 (FOUND, source S6; 2605.21606, full text v1 (2026-05-20))
  Claim (card): ` Position-weighted OPSD gains +1.0 and +1.1 Avg@12 on AIME 2024 and 2025 `

  ```text
  and AIME 2025 Avg@12 by $+1.0$ and $+1.1$ points,
  ```

  ```text
  On AIME 2024 and AIME 2025, \pwopsd{} Moderate improves Avg@12 over \opsd{} by $+1.0$ pp and $+1.1$ pp, respectively.
  ```

- A25 (FOUND, source S6; 2605.21606, full text v1 (2026-05-20))
  Claim (card): ` Finding 3: a position score predicts teacher-token reliability with AUROC 0.83 versus at most 0.57 for local uncertainty scores (Qwen3-4B setting) `

  ```text
  On Qwen3-4B, we find that an oriented within-sequence position score is the strongest tested predictor of teacher-token reliability, reaching an area-under-ROC-curve (AUROC) of $0.83$ with a $95\%$ cluster-bootstrap interval of $[0.66,0.95]$; local uncertainty scores are at most $0.57$.
  ```

  ```text
  $1-\widetilde r$ (early-position score) & $\mathbf{0.83}$ & $\mathbf{[0.66, 0.95]}$
  ```

  ```text
  $h_{\mathrm{trunc}}$ (top-$16$ valid entropy) & $0.57$ & $[0.51, 0.72]$
  ```

  ```text
  \begin{table}[t] \centering \small \caption{Branch-viability classification on Qwen3-4B.
  ```

## [7]

- A9 (FOUND, source S7; 2603.07079, full text v3 (2026-06-12))
  Claim (card): ` Entropy-aware forward/reverse KL mixing in an external-teacher setting is proposed because reverse KL reduces generation diversity `

  ```text
  However, we show that the mode-seeking property of reverse KL reduces generation diversity and yields unstable learning signals when the teacher distribution has high entropy.
  ```

  ```text
  To address this, we introduce \methodfullname~(\method), which augments the reverse KL objective with forward KL on tokens where the teacher distribution has high entropy.
  ```

- A26 (FOUND, source S7; 2603.07079, full text v3 (2026-06-12))
  Claim (card): ` Finding 3: entropy-aware distillation reports Pass@8 gains of +1.37, +2.39 and +5.05 on Qwen3-0.6B, 1.7B and 4B-Base across six math benchmarks `

  ```text
  Across six math reasoning benchmarks, this yields Pass@8 accuracy gains of $+1.37$ for Qwen3-0.6B-Base, $+2.39$ for Qwen3-1.7B-Base, and $+5.05$ for Qwen3-4B-Base compared to baseline on-policy distillation methods.
  ```

  ```text
  In particular, compared to OPD, \method~improves Avg@8 by $+1.16$ and Pass@8 by $+1.37$ on average across the six benchmarks for the Qwen3-0.6B-Base model, Avg@8 by $+0.99$ and Pass@8 by $+2.39$ for the Qwen3-1.7B-Base model, and $+1.80$ in Avg@8 and $+5.05$ in Pass@8 for the Qwen3-4B-Base model.
  ```

## [8]

- A17 (FOUND, source S8; arxiv:2607.28582, record + abstract)
  Claim (card): ` Vanilla OPSD is the beta=1 member of a family interpolating between reference policy and privileged teacher, with return-to-go credit, outperforming vanilla OPSD on mathematical benchmarks `

  ```text
  We identify a structural source of this difficulty: vanilla OPSD is precisely the $β=1$ member of a broader policy-optimization family, where $β$ weights the KL penalty anchoring the student to a reference policy.
  ```

  ```text
  We introduce $β$-OPSD and derive its optimal policy as a geometric interpolation between the reference policy and the privileged teacher.
  ```

  ```text
  Return-to-go credit assignment further aligns token updates with the sequence-level objective while retaining the simplicity of OPSD.
  ```

  ```text
  Experiments on mathematical reasoning benchmarks show that $β$-OPSD consistently outperforms vanilla OPSD, improving optimization stability and downstream reasoning performance.
  ```

## [9]

- A20 (FOUND, source S9; arxiv:2606.04036, record + abstract)
  Claim (card): ` A policy-gradient hybrid combining verifier advantages, reverse KL to the teacher and reference KL reports better stability and performance than RLVR and self-distillation baselines `

  ```text
  We therefore propose SDPG, a self-distilled policy-gradient framework that combines group-relative verifier advantages with normalized standard deviation, exact full-vocabulary on-policy self-distillation, as well as reference-policy KL regularization.
  ```

  ```text
  Empirically, SDPG improves stability and performance over RLVR and self-distillation baselines.
  ```

  ```text
  Actually, it can be instantiated as an auxiliary full-vocabulary student-to-teacher reverse Kullback-Leibler divergence loss.
  ```

## [10]

- A18 (FOUND, source S10; 2603.23871, full text v1 (2026-03-25))
  Claim (card): ` Privileged self-distillation applied only to all-fail prompts yields pass@4 +0.8 to +1.1 % and pass@8 +0.4 to +1.7 % while keeping greedy accuracy (Qwen2.5-Math-1.5B-Instruct) `

  ```text
  On each training step, HDPO identifies prompts where all rollouts fail, generates privileged rollouts by providing the model with ground-truth information, filters for correct solutions, and distills the teacher's token-level distribution into the student.
  ```

  ```text
  Experiments on OpenMathInstruct-2 with Qwen2.5-Math-1.5B-Instruct show that HDPO consistently improves coverage metrics
  ```

  ```text
  (\textit{pass@4} by $+0.8$--$1.1\%$, \textit{pass@8} by $+0.4$--$1.7\%$) while maintaining greedy accuracy
  ```

## [11]

- A21 (FOUND, source S11; 2605.10781, full text v1 (2026-05-11))
  Claim (card): ` On successful rollouts the teacher mechanism overwrites the student's own choices; reversing the signal on correct rollouts is proposed `

  ```text
  While this guidance is useful when the student has failed, on successful rollouts, the same mechanism instead overwrites the student's choices and suppresses it's own reasoning.
  ```

  ```text
  Therefore, we propose reading the original self-distillation signal in reverse: when the student succeeds along a path the teacher would not have predicted, these tokens reflect its \emph{self-driven reasoning}.
  ```

  ```text
  Building on this, we propose RLRT (RLVR with Reversed Teacher), which augments GRPO by reinforcing these tokens on correct rollouts.
  ```

## [12]

- A10 (FOUND, source S12; 2608.18271, full text v1 (2026-08-18))
  Claim (card): ` The correct reference gave no consistent benefit in OPSD and a solution from another problem can outperform the correct solution on several math benchmarks (Qwen3 1.7B-8B) `

  ```text
  The correct reference does not provide a consistent performance benefit across teacher generation modes, model sizes, and training datasets.
  ```

  ```text
  Students can improve without the correct reference, and a solution from another problem can outperform the correct solution on several mathematical reasoning benchmarks.
  ```

  ```text
  We perform OPSD experiments on science and mathematics datasets using Qwen3 models ranging from 1.7B to 8B.
  ```

- A29 (FOUND, source S12; 2608.18271, full text v1 (2026-08-18))
  Claim (card): ` Finding 4 verdict: the correct full solution is not necessary and not reliably best; a solution from another problem can outperform it `

  ```text
  The experiments provide three forms of evidence. First, students can improve without the correct reference, and a solution from another problem can outperform the correct solution.
  ```

  ```text
  Students can improve without the correct reference, and a solution from another problem can outperform the correct solution on several mathematical reasoning benchmarks.
  ```

  ```text
  Whether the correct reference improves performance depends on the teacher's generation mode, the model size, and the training dataset.
  ```

## [13]

- A11 (FOUND, source S13; 2608.09228, full text v1 (2026-08-10))
  Claim (card): ` OP2SD, using a problem and solution from a different example, improves over the base model across three models and three math benchmarks and stays competitive with OPSD `

  ```text
  paired reference with a problem and solution from a different example, while preserving the student rollout, teacher, and
  ```

  ```text
  Across three models and three mathematics benchmarks, \method{} improves over the base model, remains competitive with OPSD.
  ```

- A12 (FOUND, source S13; 2608.09228, full text v1 (2026-08-10))
  Claim (card): ` OPSD gains do not necessarily come from access to the reference solution; the teacher's context-induced behaviour is an important factor `

  ```text
  The success of \method{} implies that OPSD gains do not necessarily come from access to the reference solution, and that the teacher's context-induced behavior is an important factor.
  ```

## [14]

- A13 (FOUND, source S14; arxiv:2608.01589, record + abstract)
  Claim (card): ` Trajectory-grounded guidance gives the highest aggregate question-only accuracy among compared methods, beating the full solution `

  ```text
  Across three mathematical reasoning benchmarks and model scales ranging from 1.7B to 8B, PS-OPSD achieves the highest aggregate question-only accuracy among the compared methods.
  ```

  ```text
  We propose Problem-Space-Guided OPSD (PS-OPSD), which replaces the complete solution with trajectory-grounded guidance describing the initial state, goal conditions, constraints, and a selected state-transition path.
  ```

## [15]

- A14 (FOUND, source S15; 2605.11458, full text v3 (2026-06-09))
  Claim (card): ` Full teacher exposure is not reliably the best choice and teacher-student mismatch grows monotonically with exposure `

  ```text
  A controlled fixed-exposure sweep makes this concrete on two fronts: 1) full exposure is not reliably the best choice, and 2) student--teacher mismatch grows monotonically as the teacher sees more privileged reasoning.
  ```

- A15 (FOUND, source S15; 2605.11458, full text v3 (2026-06-09))
  Claim (card): ` A learnable reveal ratio adds +0.95, +2.05 and +2.33 Avg@12 over OPSD on AIME 24, AIME 25 and HMMT 25 for Qwen3-1.7B, 4B and 8B `

  ```text
  Experiments on AIME\,24, AIME\,25, and HMMT\,25 across Qwen3-\{1.7B, 4B, 8B\} show that \methodname{} consistently outperforms competitive self-distillation and RL baselines
  ```

  ```text
  improving over OPSD by $+0.95$, $+2.05$, and $+2.33$ Average@12 points respectively
  ```

## [16]

- A19 (FOUND, source S16; arxiv:2606.15455, record + abstract)
  Claim (card): ` In RLVR, Pass@1 improves while high-k Pass@k degrades under overtraining; restricting updates to zero-success problems lifts Pass@256 above the base model `

  ```text
  However, RLVR often suffers from \emph{diversity collapse}: Pass@$1$ improves while high-$k$ Pass@$k$ degrades, which is viewed as a narrowing of the model's reasoning boundary.
  ```

  ```text
  Under a standard setup with few rollouts per problem, even a single observed success places a problem in a nearly saturated regime for high-$k$ Pass@$k$, so most updates in standard RLVR are overtraining from the boundary perspective.
  ```

  ```text
  Interventionally, restricting updates to problems with zero observed success lifts Pass@$256$ above the base model on difficult benchmarks; observationally, a non-trivial fraction of initially unsolvable problems become solvable during standard RLVR training.
  ```

## [17]

- A28 (FOUND, source S17; arxiv:2605.29198, record + abstract)
  Claim (card): ` Finding 3: a contrastive method assigns per-token credit by contrasting positive and negative prompts and also covers text-to-image `

  ```text
  To address this issue, we propose Guidance Contrastive Policy Optimization (GCPO), a novel algorithm that enables per-token credit assignment by contrasting model predictions under positive and negative prompts.
  ```

  ```text
  Through extensive experiments, GCPO consistently outperforms GRPO and DAPO baselines on both text-to-image generation and chain-of-thought reasoning benchmarks, demonstrating its effectiveness as a general and scalable optimization strategy for discrete policy learning.
  ```

## [18]

- A27 (FOUND, source S18; arxiv:2608.09263, record + abstract)
  Claim (card): ` Finding 3: the title states privileged likelihood is not automatically value and proposes three checks for token credit in OPSD; content not specified (title only) `

  ```text
  Privileged Likelihood Is Not Automatically Value: Three Checks for Token Credit in On-Policy Self-Distillation
  ```

