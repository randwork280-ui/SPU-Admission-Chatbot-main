import json
import logging
import os
import time
from datetime import datetime
from typing import Dict

import requests
from openai import OpenAI

# --- Configuration ---
CHATBOT_URL = os.getenv("CHATBOT_URL", "http://localhost:5005/chat")
DATASET_PATH = os.getenv("EVAL_DATASET_PATH", "eval_dataset.json")
DELAY_BETWEEN_QUESTIONS = int(os.getenv("EVAL_DELAY_SECONDS", "5"))

OUTPUT_PATH = os.getenv("EVAL_OUTPUT_PATH", "evaluation_report2.json")
MARKDOWN_REPORT_PATH = os.getenv("EVAL_MARKDOWN_REPORT_PATH", "evaluation_report2.md")

# OpenAI judge configuration
JUDGE_MODEL = os.getenv("OPENAI_EVAL_MODEL", "gpt-4.1-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

if not OPENAI_API_KEY:
    logger.error("OPENAI_API_KEY not found. Evaluation cannot run.")
    raise SystemExit(1)

client = OpenAI(api_key=OPENAI_API_KEY)

JUDGE_SYSTEM_PROMPT = """You are an impartial judge evaluating a university admission chatbot's response.
Your goal is to provide three scores (0, 1, or 2) for the following criteria:

1. Completeness: Does the answer address everything in the question?
2. Grounding: Is the answer derived ONLY from the provided context (Ground Truth)?
3. Correctness: Is the answer factually consistent with the Ground Truth?

Score Scale:
- 0: Poor / Completely Incorrect / Hallucinated
- 1: Partially Correct / Acceptable but incomplete
- 2: Perfect / Fully correct and grounded

Your output MUST be a valid JSON object only, in this format:
{
  "completeness": score,
  "grounding": score,
  "correctness": score,
  "reasoning": "Brief explanation for the scores"
}"""


def query_chatbot(question: str) -> Dict:
    """Send a question to the live chatbot service."""
    try:
        response = requests.post(CHATBOT_URL, json={"query": question}, timeout=30)
        if response.status_code == 200:
            return response.json()

        logger.error("Chatbot returned error %s: %s", response.status_code, response.text)
        return {"answer": "Error calling chatbot", "sources": []}
    except Exception as e:
        logger.error("Failed to connect to chatbot: %s", e)
        return {"answer": "Connection failed", "sources": []}


def judge_response(item: Dict, bot_response: str) -> Dict:
    """Use OpenAI as an LLM judge to score one interaction."""
    user_prompt = f"""
QUESTION: {item["question"]}
GROUND TRUTH (Reference): {item["ground_truth_answer"]}
CHATBOT ANSWER: {bot_response}

Please judge the chatbot answer based on the ground truth provided.
"""
    try:
        completion = client.responses.create(
            model=JUDGE_MODEL,
            input=[
                {"role": "developer", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_output_tokens=500,
            temperature=0.1,
        )

        judge_content = (completion.output_text or "").strip()
        if "{" in judge_content:
            judge_content = judge_content[judge_content.find("{"):judge_content.rfind("}") + 1]

        return json.loads(judge_content)
    except Exception as e:
        logger.error("Judging failed for ID %s: %s", item.get("id"), e)
        return {
            "completeness": 0,
            "grounding": 0,
            "correctness": 0,
            "reasoning": "Judging Error",
        }


def run_evaluation():
    logger.info("Starting evaluation pipeline with judge model: %s", JUDGE_MODEL)

    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    results = []
    category_metrics = {}

    for item in dataset:
        logger.info("Testing ID %s: %s...", item["id"], item["question"][:50])

        bot_output = query_chatbot(item["question"])
        bot_answer = bot_output.get("answer", "")
        judge_scores = judge_response(item, bot_answer)

        result = {
            "id": item["id"],
            "question": item["question"],
            "category": item["category"],
            "language": item["language"],
            "ground_truth": item["ground_truth_answer"],
            "bot_answer": bot_answer,
            "scores": judge_scores,
        }
        results.append(result)

        category = item["category"]
        if category not in category_metrics:
            category_metrics[category] = {
                "count": 0,
                "completeness": 0,
                "grounding": 0,
                "correctness": 0,
            }

        category_metrics[category]["count"] += 1
        category_metrics[category]["completeness"] += judge_scores.get("completeness", 0)
        category_metrics[category]["grounding"] += judge_scores.get("grounding", 0)
        category_metrics[category]["correctness"] += judge_scores.get("correctness", 0)

        logger.info("Waiting %s seconds before next item...", DELAY_BETWEEN_QUESTIONS)
        time.sleep(DELAY_BETWEEN_QUESTIONS)

    for category, metrics in category_metrics.items():
        count = metrics["count"]
        metrics["avg_completeness"] = round(metrics["completeness"] / count, 2)
        metrics["avg_grounding"] = round(metrics["grounding"] / count, 2)
        metrics["avg_correctness"] = round(metrics["correctness"] / count, 2)

    final_output = {
        "timestamp": datetime.now().isoformat(),
        "judge_model": JUDGE_MODEL,
        "totals": category_metrics,
        "details": results,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)

    generate_markdown_report(final_output)
    logger.info("Evaluation complete. Results saved to %s", OUTPUT_PATH)


def generate_markdown_report(data: Dict):
    """Create a human-readable report."""
    with open(MARKDOWN_REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("# SPU Admission Chatbot - Evaluation Report\n\n")
        f.write(f"Generated on: {data['timestamp']}\n\n")
        f.write(f"Judge model: `{data['judge_model']}`\n\n")

        f.write("## 1. Aggregate Statistics (0-2 Scale)\n\n")
        f.write("| Category | Count | Completeness | Grounding | Correctness |\n")
        f.write("| :--- | :---: | :---: | :---: | :---: |\n")

        for category, metrics in data["totals"].items():
            f.write(
                f"| {category.capitalize()} | {metrics['count']} | "
                f"{metrics['avg_completeness']} | {metrics['avg_grounding']} | "
                f"{metrics['avg_correctness']} |\n"
            )

        f.write("\n\n## 2. Key Failure Analysis (Scored 0)\n\n")
        failures = [d for d in data["details"] if d["scores"].get("correctness") == 0]
        if not failures:
            f.write("No major correctness failures detected.\n")

        for failure in failures[:5]:
            f.write(f"### ID {failure['id']} ({failure['category']})\n")
            f.write(f"- **Q:** {failure['question']}\n")
            f.write(f"- **Bot:** {failure['bot_answer']}\n")
            f.write(f"- **Reasoning:** {failure['scores'].get('reasoning', '')}\n\n")


if __name__ == "__main__":
    run_evaluation()
