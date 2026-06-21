# Evaluation

The evaluation system has two layers:

1. Smoke evaluation: `eval_dataset.json`
2. Gold evaluation: future `eval_dataset.gold.json`

The smoke dataset is source-independent and checks refusal behavior, prompt-injection resistance, privacy-sensitive requests, fraud/academic-integrity requests, and Arabic/English language matching.

The gold dataset must be built only after reviewed source documents are available in `Data/manifest.json`. Do not create admissions ground-truth answers from memory or model output.

## Commands

Validate the default dataset:

```bash
python evaluate_system.py --validate-only
```

Run smoke evaluation against a running QA service:

```bash
python evaluate_system.py --judge-mode rules --fail-on-threshold
```

Run future source-backed evaluation with an LLM judge:

```bash
$env:EVAL_DATASET_PATH="eval_dataset.gold.json"
$env:EVAL_JUDGE_MODE="llm"
$env:OPENAI_API_KEY="..."
python evaluate_system.py --fail-on-threshold
```

Reports are written to `evaluation/reports/` by default.

See [evaluation/README.md](../evaluation/README.md) for the full workflow.
