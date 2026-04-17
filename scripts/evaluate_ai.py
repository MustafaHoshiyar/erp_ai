import json
import os
import sys

# Add parent directory to path to import local modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_engine import generate_sql

DATASET_PATHS = (
    os.path.join(os.path.dirname(__file__), "golden_dataset.json"),
    os.path.join(os.path.dirname(__file__), "phase1_regression_dataset.json"),
)


def load_dataset():
    dataset = []

    for dataset_path in DATASET_PATHS:
        if not os.path.exists(dataset_path):
            continue

        with open(dataset_path, "r", encoding="utf-8") as f:
            dataset.extend(json.load(f))

    if not dataset:
        expected = ", ".join(DATASET_PATHS)
        print(f"Error: Could not find any evaluation dataset. Checked: {expected}")
        sys.exit(1)

    return dataset


def _normalize(text):
    return (text or "").upper()


def run_evaluation():
    dataset = load_dataset()
    print(f"\nStarting Motherbrain Evaluation Pipeline ({len(dataset)} tests)")
    print("-" * 50)

    passed = 0
    failed = 0

    for item in dataset:
        print(f"Test [{item['id']}]: '{item['prompt']}'")

        result = generate_sql(
            item["prompt"],
            history=item.get("history"),
            client_id=item.get("client_id", "EVALUATION_BOT"),
            user_id="SYSTEM_EVALUATOR",
        )

        generated_sql = result.get("sql", "")
        raw_message = result.get("message", "")
        if not generated_sql and result.get("needs_forecast"):
            generated_sql = raw_message

        test_failures = []
        expected_intent = item.get("expected_intent")
        detected_intent = result.get("detected_intent")

        if expected_intent and detected_intent != expected_intent:
            test_failures.append(
                f"intent mismatch: expected '{expected_intent}' but got '{detected_intent}'"
            )

        expects_sql = item.get("expects_sql", True)
        if expects_sql and not generated_sql:
            test_failures.append("AI did not generate SQL.")
        if not expects_sql and generated_sql:
            test_failures.append("AI generated SQL when a non-SQL response was expected.")

        normalized_sql = _normalize(generated_sql)
        normalized_message = _normalize(raw_message)

        for expected in item.get("expected_sql_contains", []):
            if expected.upper() not in normalized_sql:
                test_failures.append(f"SQL missing required logic: {expected}")

        for forbidden in item.get("expected_sql_not_contains", []):
            if forbidden.upper() in normalized_sql:
                test_failures.append(f"SQL included forbidden logic: {forbidden}")

        for expected in item.get("expected_response_contains", []):
            if expected.upper() not in normalized_message:
                test_failures.append(f"Response missing required text: {expected}")

        if test_failures:
            print("FAILED")
            for failure in test_failures:
                print(f"  - {failure}")
            if generated_sql:
                print(f"Generated SQL:\n{generated_sql}\n")
            elif raw_message:
                print(f"Generated Response:\n{raw_message}\n")
            failed += 1
        else:
            print("PASSED")
            passed += 1

        print("-" * 50)

    print("\nEVALUATION SUMMARY")
    print(f"Total Tests: {len(dataset)}")
    print(f"Passed:      {passed}")
    print(f"Failed:      {failed}")

    if failed > 0:
        print("\nWARNING: Recent updates introduced evaluation regressions.")
        print("Please review the failed tests before committing code to Motherbrain.")
        sys.exit(1)

    print("\nSUCCESS: All tests passed. Safe to deploy Motherbrain update.")
    sys.exit(0)


if __name__ == "__main__":
    run_evaluation()
