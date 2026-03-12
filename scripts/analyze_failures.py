import os
import sys
import json
import glob
from groq import Groq
from openai import OpenAI
from dotenv import load_dotenv

# Add parent directory to path to import local modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

AI_PROVIDER = os.getenv("AI_PROVIDER", "openai").lower()
AI_MODEL    = os.getenv("AI_MODEL", "gpt-4o")

if AI_PROVIDER == "groq":
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
elif AI_PROVIDER == "openai":
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
else:
    raise ValueError(f"Unsupported AI_PROVIDER: {AI_PROVIDER}")

print(f"[Motherbrain Analyzer] Using provider: {AI_PROVIDER}, model: {AI_MODEL}")

# In a real Motherbrain server, this script would read from a central database.
# For our mock setup, we will read the JSON files that telemetry_sync saved.
# The logs are saved by main.py in the root 'telemetry_logs' directory.
LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "telemetry_logs")

def categorize_error(record: dict) -> dict:
    prompt = f"""
You are the central "Motherbrain" AI for an ERP system.
Analyze the following failed query and categorize the root cause.

User Prompt: {record.get('user_prompt')}
Generated SQL: {record.get('anonymized_sql')}
Error Message: {record.get('error_message')}
User Feedback/Comment: {record.get('feedback_comment', 'None provided')}

Based ONLY on the data above, select the most accurate Category and provide a 1-sentence recommended fix that we could add to the Global SYSTEM_PROMPT.

Categories to choose from:
1. Schema Hallucination (Used a table or column that doesn't exist)
2. Semantic Misunderstanding (Misunderstood business logic, e.g., calculated Profit wrong)
3. Syntax Error (Bad SQL syntax, e.g., missing comma, wrong MariaDB function)
4. Other/Unknown

Return ONLY a raw JSON object with this exact format:
{{
    "category": "String category name from the list above",
    "recommendation": "1 sentence fix for the system prompt"
}}
"""
    
    try:
        response = client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": "You are an AI diagnostic bot. Output strictly JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )
        raw_output = response.choices[0].message.content.strip()
        
        # Remove markdown ticks if present
        if raw_output.startswith("```json"):
            raw_output = raw_output[7:-3].strip()
        elif raw_output.startswith("```"):
            raw_output = raw_output[3:-3].strip()
            
        return json.loads(raw_output)
    except Exception as e:
        print(f"Error categorizing record {record.get('message_id')}: {e}")
        return {"category": "Error in Analysis", "recommendation": str(e)}

def run_analysis():
    if not os.path.exists(LOGS_DIR):
        print(f"No telemetry logs directory found at {LOGS_DIR}. Have you run telemetry_sync.py yet?")
        return
        
    log_files = glob.glob(os.path.join(LOGS_DIR, "motherbrain_mock_log_*.json"))
    
    if not log_files:
        print(f"No mock logs found in {LOGS_DIR}.")
        return
        
    # Analyze the most recent file
    latest_file = max(log_files, key=os.path.getctime)
    print(f"\n🧠 [MOTHERBRAIN] Analyzing latest telemetry payload: {os.path.basename(latest_file)}")
    
    try:
        with open(latest_file, "r") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Failed to read log {latest_file}: {e}")
        return

    print(f"Found {len(data)} fail records to analyze.")
    print("-" * 50)
    
    for record in data:
        print(f"Analyzing Message ID: {record.get('message_id')}")
        print(f"Prompt: '{record.get('user_prompt')}'")
        print("Categorizing with AI...")
        
        analysis = categorize_error(record)
        
        print(f"Category:       {analysis.get('category')}")
        print(f"Recommendation: {analysis.get('recommendation')}")
        print("-" * 50)

if __name__ == "__main__":
    run_analysis()
