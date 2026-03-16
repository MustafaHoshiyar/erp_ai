from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from ai_engine import generate_sql, generate_chart_config, classify_prompt_intent, build_non_report_response
from sql_validator import validate_sql
from erp_client import run_query
from database import SessionLocal, SavedReport, get_db, Conversation, ConversationMessage
from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException, BackgroundTasks
from memory_manager import backfill_embeddings_in_background

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

token_stats = {
    "total_tokens": 0,
    "request_count": 0,
    "history": []
}

@app.get("/")
def home():
    return RedirectResponse(url="/static/login.html", status_code=302)

@app.get("/health")
def health():
    return {"status": "ok", "service": "erp_ai"}
    
@app.get("/api/config")
def get_config():
    import os
    from dotenv import load_dotenv
    load_dotenv()
    erp_url = os.getenv("ERP_URL", "").rstrip("/")
    return {
        "environment": os.getenv("ENVIRONMENT", "development"),
        "insights_url": f"{erp_url}/insights/dashboards"
    }
    
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

class PromptRequest(BaseModel):
    prompt: str
    history: Optional[List[Dict[str, str]]] = None
    client_id: Optional[str] = "DEMO_CLIENT_123"
    app_name: Optional[str] = None
    conversation_id: Optional[int] = None

@app.post("/generate-report")
async def generate_report(request: PromptRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    intent_meta = classify_prompt_intent(request.prompt, request.history)
    detected_intent = intent_meta.get("intent", "report")

    conversation_id = request.conversation_id
    if not conversation_id:
        app_name = request.app_name
        if not app_name:
            from erp_client import get_app_name
            app_name = await get_app_name()
            
        new_conv = Conversation(client_id=request.client_id, app_name=app_name)
        db.add(new_conv)
        db.commit()
        db.refresh(new_conv)
        conversation_id = new_conv.id

    msg = ConversationMessage(
        conversation_id=conversation_id,
        user_prompt=request.prompt,
        detected_intent=detected_intent
    )

    if detected_intent in {"chat", "clarification_needed", "unsupported"}:
        msg.assistant_response = build_non_report_response(request.prompt, detected_intent)
        msg.execution_status = "skipped"
        db.add(msg)
        db.commit()
        db.refresh(msg)

        return {
            "conversation_id": conversation_id,
            "message_id": msg.id,
            "intent": detected_intent,
            "sql": None,
            "data": None,
            "message": msg.assistant_response,
            "tokens_used": 0
        }

    from erp_client import get_default_currency_info
    currency_info = await get_default_currency_info()
    result = generate_sql(request.prompt, request.history, request.client_id, currency=currency_info["code"], currency_symbol=currency_info["symbol"])
    tokens_used = result.get("tokens_used", 0)

    if tokens_used:
        token_stats["total_tokens"] += tokens_used
        token_stats["request_count"] += 1
        token_stats["history"].append({
            "tokens": tokens_used,
            "prompt": request.prompt[:80]
        })
        if len(token_stats["history"]) > 50:
            token_stats["history"] = token_stats["history"][-50:]

    msg.generated_sql = result.get("sql")
    msg.assistant_response = result.get("message")
    msg.tokens_used = tokens_used
    msg.detected_intent = result.get("detected_intent", detected_intent)
    db.add(msg)
    db.commit()
    db.refresh(msg)

    if not result.get("sql"):
        msg.execution_status = "error"
        msg.error_message = "No SQL generated"
        db.commit()
        return {
            "conversation_id": conversation_id,
            "message_id": msg.id,
            "intent": msg.detected_intent,
            "sql": None,
            "data": None,
            "message": result.get("message"),
            "tokens_used": tokens_used
        }

    try:
        validated_sql = validate_sql(result["sql"])
        data = await run_query(validated_sql)

        if result.get("needs_forecast"):
            import re
            from forecaster import generate_forecast
            match = re.search(r"FORECAST:\s*(.+?),\s*(.+?),\s*(\d+)", result.get("message", ""))
            if match:
                date_col = match.group(1).strip()
                target_col = match.group(2).strip()
                periods = int(match.group(3).strip())
                print(f"[Main] Running Python forecast: {date_col}, {target_col}, for {periods} periods.")
                data = generate_forecast(data, date_col, target_col, periods)

        msg.execution_status = "success"
        db.commit()
        background_tasks.add_task(backfill_embeddings_in_background, request.client_id)
    except Exception as e:
        msg.execution_status = "error"
        msg.error_message = str(e)
        db.commit()
        failed_sql = locals().get("validated_sql") or result.get("sql")
        return {
            "conversation_id": conversation_id,
            "message_id": msg.id,
            "intent": msg.detected_intent,
            "sql": failed_sql,
            "data": None,
            "message": result.get("message"),
            "error": str(e),
            "tokens_used": tokens_used
        }

    return {
        "conversation_id": conversation_id,
        "message_id": msg.id,
        "intent": msg.detected_intent,
        "sql": validated_sql,
        "data": data,
        "message": result.get("message"),
        "tokens_used": tokens_used
    }

class ChartConfigRequest(BaseModel):
    columns: List[str]
    data_sample: List[Dict[str, Any]]
    dataset_summary: Optional[Dict[str, Any]] = None

@app.post("/api/generate_chart_config")
async def api_generate_chart_config(request: ChartConfigRequest):
    try:
        from erp_client import get_default_currency_info
        currency_info = await get_default_currency_info()
        config_str = generate_chart_config(request.columns, request.data_sample, request.dataset_summary, currency=currency_info["code"], currency_symbol=currency_info["symbol"])
        import json
        config_json = json.loads(config_str)
        return config_json
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class SaveReportRequest(BaseModel):
    client_id: str
    name: str
    original_prompt: str
    sql_query: str
    chart_config: Optional[Dict[str, Any]] = None

@app.post("/api/reports/save")
def save_report(request: SaveReportRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        new_report = SavedReport(
            client_id=request.client_id,
            name=request.name,
            original_prompt=request.original_prompt,
            sql_query=request.sql_query,
            chart_config=request.chart_config
        )
        db.add(new_report)
        db.commit()
        db.refresh(new_report)
        background_tasks.add_task(backfill_embeddings_in_background, request.client_id)
        return {"status": "success", "id": new_report.id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/reports/insights-dashboards")
async def get_insights_dashboards():
    from frappe_insights import get_all_dashboards
    try:
        dashboards = await get_all_dashboards()
        return {"status": "success", "dashboards": dashboards}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/reports/{client_id}")
def get_saved_reports(client_id: str, db: Session = Depends(get_db)):
    reports = db.query(SavedReport).filter(SavedReport.client_id == client_id).order_by(SavedReport.created_at.desc()).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "original_prompt": r.original_prompt,
            "sql_query": r.sql_query,
            "chart_config": r.chart_config,
            "created_at": r.created_at.isoformat() if r.created_at else None
        }
        for r in reports
    ]

@app.delete("/api/reports/{report_id}")
def delete_saved_report(report_id: int, db: Session = Depends(get_db)):
    report = db.query(SavedReport).filter(SavedReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
        
    try:
        db.delete(report)
        db.commit()
        return {"status": "success"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/schema/refresh")
@app.get("/api/schema/refresh")
def refresh_schema():
    """Manually triggers a fresh fetch of the client's custom schema from ERPNext."""
    from schema_fetcher import fetch_and_cache_local_schema
    try:
        schema = fetch_and_cache_local_schema()
        return {
            "status": "success",
            "custom_doctypes": len(schema.get("custom_doctypes", [])),
            "custom_fields": len(schema.get("custom_fields", []))
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Schema refresh failed: {str(e)}")

@app.post("/api/reports/execute/{report_id}")
async def execute_saved_report(report_id: int, db: Session = Depends(get_db)):
    report = db.query(SavedReport).filter(SavedReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
        
    try:
        validated_sql = validate_sql(report.sql_query)
        data = await run_query(validated_sql)
        
        return {
            "id": report.id,
            "name": report.name,
            "original_prompt": report.original_prompt,
            "sql": validated_sql,
            "chart_config": report.chart_config,
            "data": data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error executing report: {str(e)}")

@app.get("/api/currency-info")
async def get_currency_info():
    from erp_client import get_default_currency_info
    return await get_default_currency_info()

@app.get("/api/token-stats")
def get_token_stats():
    return {
        "total_tokens": token_stats["total_tokens"],
        "request_count": token_stats["request_count"],
        "history": token_stats["history"][-10:]
    }

@app.post("/api/token-stats/reset")
def reset_token_stats():
    token_stats["total_tokens"] = 0
    token_stats["request_count"] = 0
    token_stats["history"] = []
    return {"status": "success"}

class ExportInsightsRequest(BaseModel):
    title: str
    sql: str
    chart_type: str = "Bar"
    dashboard_name: str = "ERP AI Dashboard"
    x_col: Optional[str] = None
    y_cols: Optional[List[str]] = None

@app.post("/api/reports/export-insights")
async def export_to_insights(request: ExportInsightsRequest):
    from frappe_insights import export_chart_and_dashboard_to_insights
    try:
        validate_sql(request.sql)
        result = await export_chart_and_dashboard_to_insights(
            title=request.title,
            sql=request.sql,
            chart_type=request.chart_type,
            dashboard_name=request.dashboard_name,
            x_col=request.x_col,
            y_cols=request.y_cols
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/api/login")
async def login(req: LoginRequest):
    try:
        from erp_client import ERP_URL
        import httpx
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{ERP_URL}/api/method/login",
                json={"usr": req.username, "pwd": req.password}
            )
            data = resp.json()
            
            if resp.status_code == 200 and data.get("message") == "Logged In":
                return {
                    "token": data.get("full_name", req.username) + "-auth-token",
                    "email": req.username
                }
                
            raise HTTPException(status_code=401, detail="Invalid credentials for Frappe")
            
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to connect to ERPNext: {str(exc)}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class FeedbackRequest(BaseModel):
    message_id: int
    feedback: int
    comment: Optional[str] = None

@app.post("/api/conversations/feedback")
def submit_feedback(request: FeedbackRequest, db: Session = Depends(get_db)):
    msg = db.query(ConversationMessage).filter(ConversationMessage.id == request.message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
        
    msg.user_feedback = request.feedback
    if request.comment:
        msg.feedback_comment = request.comment
        
    db.commit()
    return {"status": "success", "message_id": msg.id, "feedback": msg.user_feedback}


class MotherbrainTelemetryPayload(BaseModel):
    telemetry_data: List[Dict[str, Any]]

@app.post("/api/motherbrain/ingest")
def mock_motherbrain_ingest(payload: MotherbrainTelemetryPayload):
    import json
    import os
    print("\n" + "="*50)
    print("📡 [MOTHERBRAIN] Received Telemetry Data:")
    print(f"Total Records: {len(payload.telemetry_data)}")
    
    import datetime
    logs_dir = os.path.join(os.path.dirname(__file__), "telemetry_logs")
    os.makedirs(logs_dir, exist_ok=True)
    filename = os.path.join(logs_dir, f"motherbrain_mock_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    
    with open(filename, "w") as f:
        json.dump(payload.telemetry_data, f, indent=4)
        
    print(f"Saved payload to {filename} for inspection.")
    print("="*50 + "\n")
    
    return {"status": "success", "message": "Motherbrain received data", "records_processed": len(payload.telemetry_data)}

class ContextOverrideRequest(BaseModel):
    client_id: str
    term: str
    sql_logic: str
    description: Optional[str] = None

@app.post("/api/context-overrides")
def create_context_override(request: ContextOverrideRequest, db: Session = Depends(get_db)):
    from database import ClientContextOverride
    try:
        new_override = ClientContextOverride(
            client_id=request.client_id,
            term=request.term,
            sql_logic=request.sql_logic,
            description=request.description
        )
        db.add(new_override)
        db.commit()
        db.refresh(new_override)
        return {"status": "success", "id": new_override.id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/context-overrides/{client_id}")
def get_context_overrides(client_id: str, db: Session = Depends(get_db)):
    from database import ClientContextOverride
    overrides = db.query(ClientContextOverride).filter(ClientContextOverride.client_id == client_id).order_by(ClientContextOverride.created_at.desc()).all()
    return [
        {
            "id": r.id,
            "term": r.term,
            "sql_logic": r.sql_logic,
            "description": r.description
        }
        for r in overrides
    ]

# --- Conversation History Endpoints ---

@app.get("/api/conversations/{client_id}")
def get_conversations(client_id: str, db: Session = Depends(get_db)):
    """Fetch all conversation heads for a specific client."""
    convs = db.query(Conversation).filter(Conversation.client_id == client_id).order_by(Conversation.created_at.desc()).all()
    
    results = []
    for c in convs:
        # Get the first message to use as a title/snippet
        first_msg = db.query(ConversationMessage).filter(ConversationMessage.conversation_id == c.id).order_by(ConversationMessage.created_at.asc()).first()
        results.append({
            "id": c.id,
            "app_name": c.app_name,
            "title": first_msg.user_prompt if first_msg else "New Conversation",
            "created_at": c.created_at.isoformat() if c.created_at else None
        })
    return results

@app.get("/api/conversations/{conversation_id}/messages")
def get_conversation_messages(conversation_id: int, db: Session = Depends(get_db)):
    """Fetch all messages for a specific conversation thread."""
    messages = db.query(ConversationMessage).filter(ConversationMessage.conversation_id == conversation_id).order_by(ConversationMessage.created_at.asc()).all()
    return [
        {
            "id": m.id,
            "user_prompt": m.user_prompt,
            "detected_intent": m.detected_intent,
            "assistant_response": m.assistant_response,
            "generated_sql": m.generated_sql,
            "execution_status": m.execution_status,
            "error_message": m.error_message,
            "user_feedback": m.user_feedback,
            "feedback_comment": m.feedback_comment,
            "created_at": m.created_at.isoformat() if m.created_at else None
        }
        for m in messages
    ]

@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: int, db: Session = Depends(get_db)):
    """Delete an entire conversation thread."""
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    try:
        db.delete(conv)
        db.commit()
        return {"status": "success"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

class ExecuteSqlRequest(BaseModel):
    sql: str

@app.post("/api/execute-sql")
async def api_execute_sql(request: ExecuteSqlRequest):
    """Securely re-execute a historical SQL query."""
    try:
        validated_sql = validate_sql(request.sql)
        data = await run_query(validated_sql)
        return {"status": "success", "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/context-overrides/{override_id}")
def delete_context_override(override_id: int, db: Session = Depends(get_db)):
    from database import ClientContextOverride
    override = db.query(ClientContextOverride).filter(ClientContextOverride.id == override_id).first()
    if not override:
        raise HTTPException(status_code=404, detail="Override not found")
        
    try:
        db.delete(override)
        db.commit()
        return {"status": "success"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
