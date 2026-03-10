from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from ai_engine import generate_sql, generate_chart_config
from sql_validator import validate_sql
from erp_client import run_query
from database import SessionLocal, SavedReport, get_db, Conversation, ConversationMessage
from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException, BackgroundTasks
from memory_manager import backfill_embeddings_in_background

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# In-memory session token usage tracker
token_stats = {
    "total_tokens": 0,
    "request_count": 0,
    "history": []  # Last N requests with token counts
}

@app.get("/")
def home():
    return {"message": "ERP AI Backend is running"}
    
@app.get("/api/config")
def get_config():
    import os
    from dotenv import load_dotenv
    load_dotenv()
    return {"environment": os.getenv("ENVIRONMENT", "development")}
    
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

class PromptRequest(BaseModel):
    prompt: str
    history: Optional[List[Dict[str, str]]] = None
    client_id: Optional[str] = "DEMO_CLIENT_123"
    conversation_id: Optional[int] = None

@app.post("/generate-report")
async def generate_report(request: PromptRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    result = generate_sql(request.prompt, request.history, request.client_id)
    
    tokens_used = result.get("tokens_used", 0)
    
    # Track token usage
    if tokens_used:
        token_stats["total_tokens"] += tokens_used
        token_stats["request_count"] += 1
        token_stats["history"].append({
            "tokens": tokens_used,
            "prompt": request.prompt[:80]
        })
        # Keep only last 50 entries
        if len(token_stats["history"]) > 50:
            token_stats["history"] = token_stats["history"][-50:]

    # Handle Conversation DB Logging
    conversation_id = request.conversation_id
    if not conversation_id:
        new_conv = Conversation(client_id=request.client_id)
        db.add(new_conv)
        db.commit()
        db.refresh(new_conv)
        conversation_id = new_conv.id

    msg = ConversationMessage(
        conversation_id=conversation_id,
        user_prompt=request.prompt,
        generated_sql=result.get("sql"),
        tokens_used=tokens_used
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    # If no SQL was generated, just return the conversational message
    if not result.get("sql"):
        msg.execution_status = "error"
        msg.error_message = "No SQL generated"
        db.commit()
        return {
            "conversation_id": conversation_id,
            "message_id": msg.id,
            "sql": None,
            "data": None,
            "message": result.get("message"),
            "tokens_used": tokens_used
        }

    validated_sql = validate_sql(result["sql"])
    
    try:
        data = await run_query(validated_sql)
        
        # Check if the AI requested a Python forecast
        if result.get("needs_forecast"):
            # Try to parse the forecast parameters from the message:
            # e.g., FORECAST: Month, Sales, 6
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
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "conversation_id": conversation_id,
        "message_id": msg.id,
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
        config_str = generate_chart_config(request.columns, request.data_sample, request.dataset_summary)
        import json
        config_json = json.loads(config_str)
        return config_json
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Saved Reports Endpoints ---

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
    # Format for JSON serialization
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
        # Re-validate just in case, though it should be safe since it was saved
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

@app.get("/api/token-stats")
def get_token_stats():
    """Returns cumulative session token usage statistics."""
    return {
        "total_tokens": token_stats["total_tokens"],
        "request_count": token_stats["request_count"],
        "history": token_stats["history"][-10:]  # Last 10 for the frontend
    }

@app.post("/api/token-stats/reset")
def reset_token_stats():
    """Resets the session token usage counter."""
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
        # Validate SQL just in case
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
            # Frappe API uses usr and pwd for authentication
            resp = await client.post(
                f"{ERP_URL}/api/method/login",
                json={"usr": req.username, "pwd": req.password}
            )
            data = resp.json()
            
            # Frappe success check
            if resp.status_code == 200 and data.get("message") == "Logged In":
                # On success, return a demo token for the middleware boundary to let them in
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
    feedback: int # e.g., 1 for thumbs up, -1 for thumbs down
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

# --- Client Context Overrides ---

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
