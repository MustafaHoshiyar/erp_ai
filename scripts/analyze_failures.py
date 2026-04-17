import os
import sys
import json
from groq import Groq
from openai import OpenAI
from dotenv import load_dotenv
from sqlalchemy import or_

# Add Motherbrain backend directory to path to import models
# Assuming the user runs this from the project root or script dir
MB_BACKEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "motherbrain_admin", "backend")
sys.path.append(MB_BACKEND_DIR)

try:
    from database import SessionLocal, TelemetryEvent
except ImportError:
    print(f"Error: Could not import Motherbrain database models from {MB_BACKEND_DIR}")
    sys.exit(1)

load_dotenv()

AI_PROVIDER = os.getenv("AI_PROVIDER", "openai").lower()
AI_MODEL    = os.getenv("AI_MODEL", "gpt-4o")

def get_ai_client():
    if AI_PROVIDER == "groq":
        return Groq(api_key=os.getenv("GROQ_API_KEY"))
    else:
        return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def categorize_error(client, record: TelemetryEvent) -> dict:
    prompt = f"""
You are the central "Motherbrain" AI for an ERP system.
Analyze the following failed query and categorize the root cause.

Client: {record.client_id}
User Prompt: {record.user_prompt}
Assistant Response: {record.assistant_response or 'None'}
Generated SQL: {record.anonymized_sql}
Error Message: {record.error_message}
User Feedback/Comment: {record.feedback_comment or 'None provided'}

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
        
        if raw_output.startswith("```json"):
            raw_output = raw_output[7:-3].strip()
        elif raw_output.startswith("```"):
            raw_output = raw_output[3:-3].strip()
            
        return json.loads(raw_output)
    except Exception as e:
        print(f"Error categorizing event {record.id}: {e}")
        return {"category": "Error in Analysis", "recommendation": str(e)}

def run_analysis():
    print(f"\n🧠 [MOTHERBRAIN] Starting Batch Failure Analysis")
    print(f"Using provider: {AI_PROVIDER}, model: {AI_MODEL}")
    print("-" * 50)
    
    db = SessionLocal()
    ai_client = get_ai_client()
    
    try:
        # Fetch failures that haven't been categorized yet
        failures = db.query(TelemetryEvent).filter(
            or_(TelemetryEvent.is_true_failure == True, TelemetryEvent.user_feedback == -1),
            TelemetryEvent.ai_category == None
        ).all()
        
        if not failures:
            print("No new uncategorized failures found in the database.")
            return

        print(f"Found {len(failures)} uncategorized failures to analyze.")
        
        for record in failures:
            print(f"Analyzing Event ID: {record.id} ({record.client_id})")
            print(f"Prompt: '{record.user_prompt[:50]}...'")
            
            analysis = categorize_error(ai_client, record)
            
            record.ai_category = analysis.get("category")
            record.ai_recommendation = analysis.get("recommendation")
            
            print(f"Result: {record.ai_category}")
            print("-" * 30)
            
        db.commit()
        print(f"\n✅ Analysis complete. {len(failures)} records updated.")
        
    except Exception as e:
        print(f"Execution failed: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    run_analysis()
