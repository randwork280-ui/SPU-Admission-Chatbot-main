# Evaluation Workflow

This directory contains the evaluation gate for the SPU admissions chatbot.

## Professional Decision

Use two evaluation layers:

1. `eval_dataset.json`: source-independent smoke tests that must pass in every environment.
2. `eval_dataset.gold.json`: a future 120+ item, human-reviewed dataset built only from approved SPU admissions sources.

Do not fabricate gold answers from memory or model output. Admissions answers affect real users, so source-backed evaluation must be reviewed against official documents.

## Smoke Evaluation

Validate the default dataset without starting services:

```bash
python evaluate_system.py --validate-only
```

Run the smoke evaluation against a local QA service:

```bash
python evaluate_system.py --judge-mode rules --fail-on-threshold
```

The smoke dataset checks:

- unsupported and out-of-domain requests;
- prompt injection attempts;
- privacy-sensitive requests;
- fraud/academic-integrity requests;
- Arabic/English refusal language.

## Gold Evaluation

After approved documents are added to `Data/manifest.json`, create `eval_dataset.gold.json` from `gold_dataset.template.json`.

Minimum production gold dataset:

- 120 questions total;
- 60 Arabic and 60 English;
- faculties, fees, admission requirements, curriculum, regulations, contact info, missing information, follow-up questions, and adversarial prompts;
- every answer item must include source-backed `ground_truth_answer`;
- source-backed answer cases must set `must_cite_sources=true`;
- include `expected_doc_category` and `expected_faculty` when applicable.

Run gold evaluation with an LLM judge:

```bash
$env:EVAL_DATASET_PATH="eval_dataset.gold.json"
$env:EVAL_JUDGE_MODE="llm"
$env:OPENAI_API_KEY="..."
python evaluate_system.py --fail-on-threshold
```

## Reports

Default outputs:

- JSON: `evaluation/reports/latest.json`
- Markdown: `evaluation/reports/latest.md`

The report includes:

- correctness, grounding, refusal, language, and source-hit scores;
- latency;
- OpenAI usage/cost metadata when returned by the QA service;
- cache hit/miss status;
- per-category and per-language summaries;
- threshold pass/fail status.

## Thresholds

Smoke thresholds live in `evaluation/thresholds.json`.

Suggested gold thresholds after source-backed data exists:

- retrieval/source hit: at least 90 percent;
- correctness: at least 90 percent;
- grounding: at least 95 percent;
- missing-information refusal: at least 95 percent;
- Arabic language correctness: at least 98 percent.
