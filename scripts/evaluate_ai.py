import os
import sys
import json
from datetime import datetime

# Add parent directory to path to import local modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_engine import generate_sql

GOLDEN_DATASET_PATH = os.path.join(os.path.dirname(__file__), "golden_dataset.json")

def load_dataset():
    if not os.path.exists(GOLDEN_DATASET_PATH):
        print(f"Error: Could not find {GOLDEN_DATASET_PATH}")
        sys.exit(1)
        
    with open(GOLDEN_DATASET_PATH, 'r') as f:
        return json.load(f)

def run_evaluation():
    dataset = load_dataset()
    print(f"\n🚀 Starting Motherbrain Evaluation Pipeline ({len(dataset)} tests)")
    print("-" * 50)
    
    passed = 0
    failed = 0
    
    for item in dataset:
        print(f"Test [{item['id']}]: '{item['prompt']}'")
        
        # We pass a demo client to ensure it has no specific context overrides
        result = generate_sql(item['prompt'], client_id="EVALUATION_BOT")
        
        generated_sql = result.get('sql', "")
        if not generated_sql and result.get('needs_forecast'):
            generated_sql = result.get('message', "")
            
        if not generated_sql:
            print("❌ FAILED: AI did not generate SQL.")
            failed += 1
            print("-" * 50)
            continue
            
        # Check against expected keywords
        missing_keywords = []
        for expected in item.get('expected_sql_contains', []):
            if expected.upper() not in generated_sql.upper():
                missing_keywords.append(expected)
                
        if missing_keywords:
            print(f"❌ FAILED: Generated SQL was missing required logic: {missing_keywords}")
            print(f"Generated: \n{generated_sql}\n")
            failed += 1
        else:
            print("✅ PASSED")
            passed += 1
            
        print("-" * 50)

    print("\n📊 EVALUATION SUMMARY")
    print(f"Total Tests: {len(dataset)}")
    print(f"Passed:      {passed}")
    print(f"Failed:      {failed}")
    
    if failed > 0:
        print("\n⚠️ WARNING: Your recent updates to ai_engine.py caused regressions!")
        print("Please review the failed tests before committing code to Motherbrain.")
        sys.exit(1)
    else:
        print("\n🎉 SUCCESS: All tests passed. Safe to deploy Motherbrain update!")
        sys.exit(0)

if __name__ == "__main__":
    run_evaluation()
