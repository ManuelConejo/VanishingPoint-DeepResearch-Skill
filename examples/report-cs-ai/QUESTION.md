# Question (cs-ai plugin, standard mode, T = 2026-08-26)

How can on-policy self-distillation for language models be critically analysed, where the teacher is the model itself
conditioned on privileged information unavailable at test time? How does this asymmetry generate both a learning signal
and a bias, in particular the progressive collapse of the diversity of reasoning paths? Which three levers govern this
symptom: token weighting, the nature of the privileged information, and the dynamics of the teacher with guidance decay?
Which phenomena are well established and which points remain disputed, in the domain of mathematical reasoning?

Launched with Claude Code (`claude -p`), searchers, annex and verifier on Sonnet, the skill installed as a project skill:
"Use the vanishingpoint skill. T = 2026-08-26. <question>. Work in the directory run/ of the current project."
