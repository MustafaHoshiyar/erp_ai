import os
import sys
import json
import re
import requests
from datetime import datetime, timezone

# Add parent directory to path to import local modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal, ConversationMessage, Conversation
from dotenv import load_dotenv

load_dotenv()

# The centralized Motherbrain endpoint. 
# In production, this would be your central SaaS URL.
MOTHERBRAIN_URL = os.getenv("MOTHERBRAIN_URL")

if not MOTHERBRAIN_URL:
    raise ValueError("MOTHERBRAIN_URL is not set in the environment. Telemetry sync safely aborted to prevent syncing to localhost.")

API_KEY = os.getenv("MOTHERBRAIN_API_KEY", "dev_motherbrain_key_123")

def anonymize_sql(sql: str) -> str:
    """
    Strips raw string/number values from SQL queries to protect client PII.
    Examples:
    - "WHERE name = 'John Doe'" -> "WHERE name = ?"
    - "LIKE '%secret%'" -> "LIKE ?"
    - "target >= 500" -> "target >= ?"
    """
    if not sql:
        return ""
        
    # Replace string literals (single quoted)
    anon_sql = re.sub(r"'(?:\\.|[^'\\])*'", "?", sql)
    
    # Replace numeric literals (not part of column names)
    # This is rough; a true SQL parser is more robust, but this works for basic telemetry
    anon_sql = re.sub(r"\b\d+(?:\.\d+)?\b", "?", anon_sql)
    
    # Edge case: Keep integers for limit/offset if they are at the end, 
    # but for error telemetry, stripping everything is safer.
    return anon_sql

def run_sync():
    print(f"[{datetime.now().isoformat()}] Starting Motherbrain Telemetry Sync...")
    db = SessionLocal()
    
    try:
        # Fetch unsynced failures or negative feedback
        # A robust system would track `synced = True` flag on the message.
        # For Phase 1, we'll fetch the last 100 errors to bulk upload.
        from sqlalchemy import or_
        
        failed_messages = db.query(ConversationMessage).join(Conversation).filter(
            ConversationMessage.synced_to_motherbrain == False,
            or_(
                ConversationMessage.execution_status == "error",
                ConversationMessage.user_feedback == -1
            )
        ).order_by(ConversationMessage.created_at.desc()).limit(10).all()

        if not failed_messages:
            print("No new failed queries to sync.")
            return

        payload = []
        for msg in failed_messages:
            client_id = msg.conversation.client_id
            
            # Here we would normally fetch the *exact* schema chunk the AI used.
            # For now, we note the generic structure.
            relevant_schema = "Schema context logged in full DB (Phase 2 extension)"
            
            payload.append({
                "message_id": msg.id,
                "client_id": client_id, # Can be hashed/anonymized further
                "timestamp": msg.created_at.isoformat() if msg.created_at else None,
                "user_prompt": msg.user_prompt, # Prompts usually don't have PII, but you could add a warning.
                "anonymized_sql": anonymize_sql(msg.generated_sql),
                "execution_status": msg.execution_status,
                "error_message": msg.error_message,
                "user_feedback": msg.user_feedback,
                "feedback_comment": msg.feedback_comment
            })

        print(f"Prepared {len(payload)} records for sync.")
        
        # POST to Motherbrain
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}"
        }
        
        try:
            response = requests.post(MOTHERBRAIN_URL, json={"telemetry_data": payload}, headers=headers, timeout=10)
            
            if response.status_code == 200:
                print(f"Successfully synced {len(payload)} failures to Motherbrain: {response.json()}")
                # Mark as synced in the DB
                for msg in failed_messages:
                    msg.synced_to_motherbrain = True
                db.commit()
                print("Database updated: marked records as synced.")
            else:
                print(f"Failed to sync. Status: {response.status_code}, Body: {response.text}")
                
        except requests.exceptions.RequestException as e:
            print(f"Network error syncing to Motherbrain: {e}")

    finally:
        db.close()

if __name__ == "__main__":
    run_sync()
