import os
import sys
import json
import re
import requests
from datetime import datetime, timezone

# Add parent directory to path to import local modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal, ConversationMessage, Conversation, DATABASE_URL
from dotenv import load_dotenv

load_dotenv()

# The centralized Motherbrain base URL (recommended) or full ingest URL.
# If a base URL is provided, we will append `/api/motherbrain/ingest`.
MOTHERBRAIN_URL = os.getenv("MOTHERBRAIN_URL")
API_KEY = os.getenv("MOTHERBRAIN_API_KEY", "dev_motherbrain_key_123")

if not MOTHERBRAIN_URL:
    raise ValueError("MOTHERBRAIN_URL is not set in the environment. Telemetry sync safely aborted to prevent syncing to localhost.")

def _build_ingest_url(motherbrain_url: str) -> str:
    normalized = (motherbrain_url or "").strip().rstrip("/")
    if not normalized:
        return ""
    if normalized.lower().endswith("/api/motherbrain/ingest"):
        return normalized
    return f"{normalized}/api/motherbrain/ingest"

def anonymize_sql(sql: str) -> str:
    """
    Strips raw string/number values from SQL queries to protect client PII.
    """
    if not sql:
        return ""
    anon_sql = re.sub(r"'(?:\\.|[^'\\])*'", "?", sql)
    anon_sql = re.sub(r"\b\d+(?:\.\d+)?\b", "?", anon_sql)
    return anon_sql

def run_sync():
    print(f"[{datetime.now().isoformat()}] Starting Motherbrain Telemetry Sync...")
    db = SessionLocal()
    
    try:
        pending_messages = db.query(ConversationMessage).join(Conversation).filter(
            ConversationMessage.synced_to_motherbrain == False,
        ).order_by(ConversationMessage.created_at.desc()).limit(500).all()

        if not pending_messages:
            print("No new telemetry to sync.")
            return

        payload = []
        for msg in pending_messages:
            conversation = msg.conversation
            payload.append({
                "message_id": msg.id,
                "client_id": conversation.client_id,
                "app_name": conversation.app_name,
                "timestamp": msg.created_at.isoformat() if msg.created_at else None,
                "user_prompt": msg.user_prompt,
                "detected_intent": msg.detected_intent,
                "assistant_response": msg.assistant_response,
                "model_used": msg.model_used,
                "routing_tables": msg.routing_tables,
                "anonymized_sql": anonymize_sql(msg.generated_sql),
                "execution_status": msg.execution_status,
                "sql_generated": bool(msg.generated_sql),
                "execution_attempted": msg.execution_status in {"success", "error"},
                "is_true_failure": msg.execution_status == "error",
                "generation_ms": msg.generation_ms,
                "execution_ms": msg.execution_ms,
                "total_duration_ms": msg.total_duration_ms,
                "error_message": msg.error_message,
                "user_feedback": msg.user_feedback,
                "feedback_comment": msg.feedback_comment,
                "user_id": msg.user_id,
                "input_tokens": msg.input_tokens,
                "output_tokens": msg.output_tokens
            })

        print(f"Prepared {len(payload)} records for sync.")
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}"
        }
        ingest_url = _build_ingest_url(MOTHERBRAIN_URL)
        
        try:
            response = requests.post(ingest_url, json={"telemetry_data": payload}, headers=headers, timeout=10)
            
            if response.status_code == 200:
                print(f"Successfully synced {len(payload)} telemetry events to Motherbrain: {response.json()}")
                for msg in pending_messages:
                    msg.synced_to_motherbrain = True
                db.commit()
                print("Database updated: marked records as synced.")
            else:
                body = (response.text or "").strip()
                if len(body) > 2000:
                    body = body[:2000] + "…"
                # Do not print DATABASE_URL / full Motherbrain URL (may contain sensitive deployment info).
                print(f"Failed to sync. Status: {response.status_code}, Endpoint: /api/motherbrain/ingest, Body: {body}")
                
        except requests.exceptions.RequestException as e:
            print(f"Network error syncing to Motherbrain (Endpoint: /api/motherbrain/ingest): {e}")
            sys.exit(1)
        
        # Also exit with error if ingest failed with non-200
        # ... logic inside response block if needed, but requests.post doesn't throw on 4xx/5xx unless raise_for_status() is called


    finally:
        db.close()

if __name__ == "__main__":
    run_sync()
