import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
import time
from ai_engine import (
    generate_sql,
    generate_chart_config,
    classify_prompt_intent,
    build_non_report_response,
    normalize_sql_with_live_schema,
)
from sql_validator import validate_sql
from erp_client import run_query
from database import SessionLocal, SavedReport, get_db, Conversation, ConversationMessage, ClientConfig
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException, BackgroundTasks, Header
from memory_manager import backfill_embeddings_in_background

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

def _simplify_error_message(error_str: str) -> str:
    """Masks technical tracebacks with user-friendly messages for the frontend."""
    err = str(error_str).lower()
    if "1054" in err or "unknown column" in err:
        return "The query referenced a column that doesn't exist in the current schema. You may need to refresh the schema."
    if "1146" in err or "table" in err and "doesn't exist" in err:
        return "The query referenced a table that was not found in the database."
    if "1064" in err or "syntax" in err:
        return "There was a syntax error in the generated query. I've logged this for improvement."
    if "access denied" in err or "1045" in err or "unauthorized" in err:
        return "Database access denied. Please check your ERPNext credentials."
    if "connection" in err or "refused" in err:
        return "Could not connect to the ERPNext server. Please check the ERP URL."
        
    return "An error occurred while processing the report. The details have been logged for the developer."


def _normalize_erp_base_url(url: str) -> str:
    normalized = (url or "").strip().rstrip("/")
    if normalized.lower().endswith("/insights"):
        normalized = normalized[: -len("/insights")]
    return normalized

@app.get("/")
def home():
    return RedirectResponse(url="/static/login.html", status_code=302)

@app.get("/health")
def health():
    return {"status": "ok", "service": "erp_ai"}
    
@app.get("/api/config")
def get_config(client_id: str = "DEMO_CLIENT_123"):
    from runtime_config import get_client_runtime_config
    config = get_client_runtime_config(client_id)
    erp_url = _normalize_erp_base_url(config.get("erp_url", ""))
    environment = os.getenv("ENVIRONMENT", "development")
    # Fetch app name from override or fallback to client_id title
    app_name = config.get("app_name_override")
    if not app_name:
        app_name = client_id.replace('_', ' ').replace('-', ' ').title()

    return {
        "environment": environment,
        "app_name": app_name,
        "insights_url": f"{erp_url}/insights/dashboards" if erp_url else "",
        "allow_token_reset": environment.lower() != "production",
    }
    
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

class PromptRequest(BaseModel):
    prompt: str
    history: Optional[List[Dict[str, str]]] = None
    client_id: Optional[str] = "DEMO_CLIENT_123"
    app_name: Optional[str] = None
    user_id: Optional[str] = None
    conversation_id: Optional[int] = None


def _normalize_client_id(client_id: Optional[str]) -> str:
    normalized = (client_id or "DEMO_CLIENT_123").strip()
    return normalized or "DEMO_CLIENT_123"

@app.post("/generate-report")
async def generate_report(request: PromptRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    request_started_at = time.perf_counter()
    client_id = _normalize_client_id(request.client_id)
    intent_meta = classify_prompt_intent(request.prompt, request.history)
    detected_intent = intent_meta.get("intent", "report")

    conversation_id = request.conversation_id
    app_name = request.app_name
    
    if not conversation_id:
        if not app_name:
            from erp_client import get_app_name
            app_name = await get_app_name(client_id)
             
        new_conv = Conversation(client_id=client_id, app_name=app_name, user_id=request.user_id)
        db.add(new_conv)
        db.commit()
        db.refresh(new_conv)
        conversation_id = new_conv.id
    else:
        # Load app_name and client_id from existing conversation to ensure context is preserved
        conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if conv:
            app_name = conv.app_name
            client_id = conv.client_id

    msg = ConversationMessage(
        conversation_id=conversation_id,
        user_prompt=request.prompt,
        detected_intent=detected_intent,
        user_id=request.user_id
    )

    should_fast_skip = False
    if detected_intent in {"clarification_needed", "unsupported"}:
        should_fast_skip = True
    elif detected_intent == "chat" and not request.history:
        should_fast_skip = True

    if should_fast_skip:
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
    currency_info = await get_default_currency_info(client_id)
    generation_started_at = time.perf_counter()

    if detected_intent == "chat":
        from ai_engine import generate_chat_response
        result = generate_chat_response(request.prompt, request.history)
        result["sql"] = None
    else:
        result = generate_sql(
            request.prompt, 
            request.history, 
            client_id, 
            app_name=app_name, 
            currency=currency_info["code"], 
            currency_symbol=currency_info["symbol"]
        )

    generation_ms = round((time.perf_counter() - generation_started_at) * 1000)
    if result.get("sql"):
        original_sql = result["sql"]
        normalized_sql = normalize_sql_with_live_schema(original_sql, client_id=client_id)
        if normalized_sql != original_sql:
            result["sql"] = normalized_sql
            if (result.get("message") or "").strip() == original_sql.strip():
                result["message"] = normalized_sql
    # 4. SAVE TO HISTORY (Harden against detached instances and NameErrors)
    try:
        tokens_used = result.get("tokens_used", 0)
        if isinstance(tokens_used, dict):
            tokens_used = tokens_used.get("total", 0)

        msg.generated_sql = result.get("sql")
        msg.assistant_response = result.get("message")
        msg.tokens_used = tokens_used
        msg.input_tokens = result.get("input_tokens", 0)
        msg.output_tokens = result.get("output_tokens", 0)
        msg.detected_intent = result.get("detected_intent", detected_intent)
        msg.model_used = result.get("model_used")
        msg.routing_tables = result.get("routing_tables")
        msg.generation_ms = generation_ms
        msg.total_duration_ms = round((time.perf_counter() - request_started_at) * 1000)
        
        db.add(msg)
        db.commit()
        db.refresh(msg)

        if result.get("sql"):
            # Start background backfill for this client's learning
            background_tasks.add_task(backfill_embeddings_in_background, client_id, msg.id)
    except Exception as db_err:
        print(f"[Main] Error saving assistant response to DB: {db_err}")
        db.rollback()

    if not result.get("sql"):
        if msg.detected_intent in {"chat", "clarification_needed", "unsupported"}:
            msg.execution_status = "skipped"
            msg.error_message = None
        else:
            msg.execution_status = "error"
            msg.error_message = "No SQL generated"
        msg.total_duration_ms = round((time.perf_counter() - request_started_at) * 1000)
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
        execution_started_at = time.perf_counter()
        validated_sql = validate_sql(result["sql"])
        data = await run_query(validated_sql, client_id=client_id)
        msg.execution_ms = round((time.perf_counter() - execution_started_at) * 1000)

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
        msg.total_duration_ms = round((time.perf_counter() - request_started_at) * 1000)
        db.commit()
        background_tasks.add_task(backfill_embeddings_in_background, client_id)
    except Exception as e:
        msg.execution_status = "error"
        msg.error_message = str(e)
        msg.execution_ms = round((time.perf_counter() - execution_started_at) * 1000) if 'execution_started_at' in locals() else None
        msg.total_duration_ms = round((time.perf_counter() - request_started_at) * 1000)
        db.commit()
        # Auto-push failures to Motherbrain immediately
        background_tasks.add_task(_push_telemetry_to_motherbrain, msg.id)
        failed_sql = locals().get("validated_sql") or result.get("sql")
        return {
            "conversation_id": conversation_id,
            "message_id": msg.id,
            "intent": msg.detected_intent,
            "sql": failed_sql,
            "data": None,
            "message": result.get("message"),
            "error": _simplify_error_message(str(e)),
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
    client_id: Optional[str] = "DEMO_CLIENT_123"

@app.post("/api/generate_chart_config")
async def api_generate_chart_config(request: ChartConfigRequest):
    try:
        from erp_client import get_default_currency_info
        currency_info = await get_default_currency_info(request.client_id)
        config_str = generate_chart_config(request.columns, request.data_sample, request.dataset_summary, currency=currency_info["code"], currency_symbol=currency_info["symbol"])
        import json
        config_json = json.loads(config_str)
        return config_json
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class SaveReportRequest(BaseModel):
    client_id: str
    user_id: Optional[str] = None
    name: str
    original_prompt: str
    sql_query: str
    chart_config: Optional[Dict[str, Any]] = None

@app.post("/api/reports/save")
def save_report(request: SaveReportRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        new_report = SavedReport(
            client_id=request.client_id,
            user_id=request.user_id,
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
async def get_insights_dashboards(client_id: str = "DEMO_CLIENT_123"):
    from frappe_insights import get_all_dashboards
    try:
        dashboards = await get_all_dashboards(client_id=_normalize_client_id(client_id))
        return {"status": "success", "dashboards": dashboards}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/reports/{client_id}")
def get_saved_reports(client_id: str, user_id: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(SavedReport).filter(SavedReport.client_id == client_id)
    if user_id:
        query = query.filter(SavedReport.user_id == user_id)
    
    reports = query.order_by(SavedReport.created_at.desc()).all()
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
def refresh_schema(client_id: str = "DEMO_CLIENT_123"):
    """Manually triggers a fresh fetch of the selected client's live schema from ERPNext."""
    from schema_fetcher import fetch_and_cache_local_schema
    try:
        schema = fetch_and_cache_local_schema(client_id)
        return {
            "status": "success",
            "client_id": client_id,
            "available_doctypes": len(schema.get("available_doctypes", [])),
            "custom_doctypes": len(schema.get("custom_doctypes", [])),
            "custom_fields": len(schema.get("custom_fields", [])),
            "doctype_details": len(schema.get("doctype_details", {})),
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
        data = await run_query(validated_sql, client_id=report.client_id)
        
        return {
            "id": report.id,
            "name": report.name,
            "original_prompt": report.original_prompt,
            "sql": validated_sql,
            "chart_config": report.chart_config,
            "data": data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=_simplify_error_message(str(e)))

@app.get("/api/currency-info")
async def get_currency_info(client_id: Optional[str] = None, db: Session = Depends(get_db)):
    from erp_client import get_default_currency_info
    if not client_id:
        from database import ClientConfig
        config = db.query(ClientConfig).filter(ClientConfig.is_active == True).first()
        client_id = config.client_id if config else "DEMO_CLIENT_123"
        
    return await get_default_currency_info(client_id)

def _token_reset_allowed() -> bool:
    return os.getenv("ENVIRONMENT", "development").lower() != "production"


@app.get("/api/token-stats")
def get_token_stats(client_id: Optional[str] = None, user_id: Optional[str] = None, db: Session = Depends(get_db)):
    base_query = db.query(ConversationMessage).join(Conversation)
    if client_id:
        base_query = base_query.filter(Conversation.client_id == client_id)
    if user_id:
        base_query = base_query.filter(ConversationMessage.user_id == user_id)

    token_messages_query = base_query.filter(ConversationMessage.tokens_used.isnot(None), ConversationMessage.tokens_used > 0)
    totals = token_messages_query.with_entities(
        func.coalesce(func.sum(ConversationMessage.tokens_used), 0),
        func.count(ConversationMessage.id),
    ).one()
    recent_messages = (
        token_messages_query.order_by(ConversationMessage.created_at.desc()).limit(10).all()
    )

    return {
        "total_tokens": int(totals[0] or 0),
        "request_count": int(totals[1] or 0),
        "history": [
            {
                "tokens": int(msg.tokens_used or 0),
                "prompt": (msg.user_prompt or "")[:80],
            }
            for msg in reversed(recent_messages)
        ],
        "allow_reset": _token_reset_allowed(),
    }

@app.post("/api/token-stats/reset")
def reset_token_stats(client_id: Optional[str] = None, user_id: Optional[str] = None, db: Session = Depends(get_db)):
    if not _token_reset_allowed():
        raise HTTPException(status_code=403, detail="Token reset is disabled in production.")

    query = db.query(ConversationMessage).join(Conversation)
    if client_id:
        query = query.filter(Conversation.client_id == client_id)
    if user_id:
        query = query.filter(ConversationMessage.user_id == user_id)

    messages = query.filter(ConversationMessage.tokens_used.isnot(None), ConversationMessage.tokens_used > 0).all()
    for msg in messages:
        msg.tokens_used = None

    db.commit()
    return {"status": "success"}

@app.get("/api/metrics/baseline")
def get_baseline_metrics(client_id: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(ConversationMessage).join(Conversation)
    if client_id:
        query = query.filter(Conversation.client_id == client_id)

    messages = query.all()
    total_prompts = len(messages)
    if total_prompts == 0:
        return {
            "scope": {"client_id": client_id},
            "totals": {"prompts": 0},
            "rates": {},
            "latency_ms": {},
        }

    def avg(values):
        values = [value for value in values if value is not None]
        return round(sum(values) / len(values), 2) if values else None

    report_prompts = [m for m in messages if m.detected_intent in {"report", "forecast"}]
    chat_prompts = [m for m in messages if m.detected_intent == "chat"]
    clarification_prompts = [m for m in messages if m.detected_intent == "clarification_needed"]
    unsupported_prompts = [m for m in messages if m.detected_intent == "unsupported"]
    sql_generated = [m for m in messages if m.generated_sql]
    executed = [m for m in messages if m.execution_status in {"success", "error"}]
    successes = [m for m in messages if m.execution_status == "success"]
    failures = [m for m in messages if m.execution_status == "error"]
    negative_feedback = [m for m in messages if m.user_feedback == -1]

    return {
        "scope": {"client_id": client_id},
        "totals": {
            "prompts": total_prompts,
            "report_prompts": len(report_prompts),
            "chat_prompts": len(chat_prompts),
            "clarification_prompts": len(clarification_prompts),
            "unsupported_prompts": len(unsupported_prompts),
            "sql_generated": len(sql_generated),
            "execution_attempted": len(executed),
            "execution_successes": len(successes),
            "true_failures": len(failures),
            "negative_feedback": len(negative_feedback),
        },
        "rates": {
            "sql_generation_success_rate": round(len(sql_generated) / total_prompts, 4),
            "execution_success_rate": round(len(successes) / len(executed), 4) if executed else None,
            "true_failure_rate": round(len(failures) / total_prompts, 4),
            "negative_feedback_rate": round(len(negative_feedback) / total_prompts, 4),
        },
        "latency_ms": {
            "avg_generation_ms": avg([m.generation_ms for m in messages]),
            "avg_execution_ms": avg([m.execution_ms for m in executed]),
            "avg_total_duration_ms": avg([m.total_duration_ms for m in messages]),
        },
        "models": sorted({m.model_used for m in messages if m.model_used}),
    }

class ExportInsightsRequest(BaseModel):
    client_id: Optional[str] = "DEMO_CLIENT_123"
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
            y_cols=request.y_cols,
            client_id=_normalize_client_id(request.client_id),
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class LoginRequest(BaseModel):
    username: str
    password: str
    client_id: str

@app.post("/api/login")
async def login(req: LoginRequest):
    try:
        from runtime_config import get_client_runtime_config
        import httpx

        username = req.username.strip()
        client_id = req.client_id.strip()
        
        if not client_id:
            raise HTTPException(status_code=400, detail="Workspace ID is required")

        config = get_client_runtime_config(client_id)
        if not config or not config.get('erp_url'):
            raise HTTPException(status_code=404, detail=f"No configuration found for Workspace ID: {client_id}")

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{config['erp_url']}/api/method/login",
                json={"usr": username, "pwd": req.password}
            )
            data = resp.json()
            
            if resp.status_code == 200 and data.get("message") == "Logged In":
                return {
                    "token": data.get("full_name", username) + "-auth-token",
                    "email": username
                }
                
            raise HTTPException(status_code=401, detail="Invalid credentials for Frappe")
            
    except httpx.RequestError as exc:
        import traceback
        print(f"FAILED TO CONNECT TO ERPNext for client_id={client_id} at {config['erp_url']}")
        traceback.print_exc()
        raise HTTPException(status_code=502, detail=f"Failed to connect to ERPNext: {str(exc)}")
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

class ClientConfigRequest(BaseModel):
    client_id: str
    erp_url: str
    api_key: str
    api_secret: str
    app_name_override: Optional[str] = None
    is_active: bool = True

@app.get("/api/client-configs")
def list_client_configs(db: Session = Depends(get_db)):
    configs = db.query(ClientConfig).order_by(ClientConfig.client_id.asc()).all()
    return [
        {
            "client_id": config.client_id,
            "erp_url": config.erp_url,
            "api_key": config.api_key,
            "api_secret": config.api_secret,
            "app_name_override": config.app_name_override,
            "is_active": config.is_active,
        }
        for config in configs
    ]

@app.get("/api/client-configs/{client_id}")
def get_client_config(client_id: str, db: Session = Depends(get_db)):
    try:
        config = db.query(ClientConfig).filter(ClientConfig.client_id == client_id).first()
        if not config:
            # Let's return a special case for not found so Motherbrain knows it's empty but reachable
            return {"status": "not_initialized", "client_id": client_id}

        return {
            "client_id": config.client_id,
            "erp_url": config.erp_url,
            "api_key": config.api_key,
            "api_secret": config.api_secret,
            "app_name_override": config.app_name_override,
            "is_active": config.is_active,
        }
    except Exception as e:
        return {
            "status": "node_internal_error",
            "error": str(e),
            "internal_details": "Check edge node database connection or schema."
        }

@app.post("/api/client-configs")
def upsert_client_config(request: ClientConfigRequest, db: Session = Depends(get_db)):
    config = db.query(ClientConfig).filter(ClientConfig.client_id == request.client_id).first()
    if not config:
        config = ClientConfig(client_id=request.client_id)
        db.add(config)

    config.erp_url = request.erp_url.rstrip("/")
    config.api_key = request.api_key
    config.api_secret = request.api_secret
    config.app_name_override = request.app_name_override
    config.is_active = request.is_active
    db.commit()
    db.refresh(config)

    return {
        "status": "success",
        "client_id": config.client_id,
        "erp_url": config.erp_url,
        "api_key": config.api_key,
        "api_secret": config.api_secret,
        "app_name_override": config.app_name_override,
        "is_active": config.is_active,
    }

class FeedbackRequest(BaseModel):
    message_id: int
    feedback: int
    comment: Optional[str] = None

def _run_auto_extract_override(client_id: str, message_id: int, user_prompt: str, feedback_comment: str):
    """Background task: extract context override from user feedback and store as pending."""
    from ai_engine import auto_extract_context_override
    from database import PendingContextOverride
    import os
    result = auto_extract_context_override(client_id, message_id, user_prompt, feedback_comment)
    if not result:
        return
    db = SessionLocal()
    try:
        auto_approve = os.getenv("AUTO_APPROVE_OVERRIDES", "false").lower() == "true"
        if auto_approve:
            from database import ClientContextOverride
            new_override = ClientContextOverride(
                client_id=result["client_id"],
                term=result["term"],
                sql_logic=result["sql_logic"],
                description=result["description"],
            )
            db.add(new_override)
            print(f"[AutoExtract] AUTO-APPROVED override for '{result['term']}' (client={client_id})")
        else:
            pending = PendingContextOverride(
                client_id=result["client_id"],
                source_message_id=result["source_message_id"],
                original_prompt=result["original_prompt"],
                feedback_comment=result["feedback_comment"],
                term=result["term"],
                sql_logic=result["sql_logic"],
                description=result["description"],
                confidence=result["confidence"],
                status="pending",
            )
            db.add(pending)
            print(f"[AutoExtract] Queued pending override for '{result['term']}' (client={client_id}, confidence={result['confidence']})")
        db.commit()
    except Exception as e:
        print(f"[AutoExtract] DB save failed: {e}")
    finally:
        db.close()

class OverridePushRequest(BaseModel):
    client_id: str
    term: str
    sql_logic: str
    description: Optional[str] = None

@app.post("/api/motherbrain/push-override")
def push_override_from_motherbrain(
    request: OverridePushRequest,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """Securely receive a Context Override push from Motherbrain Admin."""
    from database import ClientContextOverride

    expected_key = os.getenv("MOTHERBRAIN_API_KEY", "dev_motherbrain_key_123")
    bearer = None
    if authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            bearer = parts[1].strip()

    provided_key = bearer or (x_api_key.strip() if x_api_key else None)
    if not provided_key or provided_key != expected_key:
        raise HTTPException(status_code=401, detail="Unauthorized (invalid Motherbrain API key)")
    
    # Check if existing term exists for this client
    existing = db.query(ClientContextOverride).filter(
        ClientContextOverride.client_id == request.client_id,
        ClientContextOverride.term.ilike(request.term)
    ).first()
    
    if existing:
        existing.sql_logic = request.sql_logic
        existing.description = request.description
    else:
        new_override = ClientContextOverride(
            client_id=request.client_id,
            term=request.term,
            sql_logic=request.sql_logic,
            description=request.description
        )
        db.add(new_override)
    
    db.commit()
    return {"status": "success", "message": f"Override for '{request.term}' pushed successfully."}


def _push_telemetry_to_motherbrain(message_id: int, force: bool = False):
    """Background task: push a single ConversationMessage record to Motherbrain."""
    import httpx, os, json
    db = SessionLocal()
    try:
        msg = db.query(ConversationMessage).filter(ConversationMessage.id == message_id).first()
        if not msg:
            return
        
        # If already synced and NOT a forced update (like feedback), skip
        if msg.synced_to_motherbrain and not force:
            return
        conv = db.query(Conversation).filter(Conversation.id == msg.conversation_id).first()
        client_id = conv.client_id if conv else "unknown"
        mb_url = os.getenv("MOTHERBRAIN_URL", "http://127.0.0.1:8005")
        mb_key = os.getenv("MOTHERBRAIN_API_KEY", "dev_motherbrain_key_123")
        payload = {
            "telemetry_data": [{
                "message_id": msg.id,
                "client_id": client_id,
                "app_name": conv.app_name if conv else None,
                "timestamp": msg.created_at.isoformat() if msg.created_at else None,
                "user_prompt": msg.user_prompt or "",
                "detected_intent": msg.detected_intent,
                "assistant_response": msg.assistant_response,
                "model_used": msg.model_used,
                "routing_tables": msg.routing_tables,
                "anonymized_sql": msg.generated_sql or "",
                "execution_status": msg.execution_status or "unknown",
                "sql_generated": bool(msg.generated_sql),
                "execution_attempted": msg.execution_status in ("success", "error"),
                "is_true_failure": msg.execution_status == "error",
                "generation_ms": msg.generation_ms,
                "execution_ms": msg.execution_ms,
                "total_duration_ms": msg.total_duration_ms,
                "error_message": msg.error_message,
                "user_feedback": msg.user_feedback,
                "feedback_comment": msg.feedback_comment,
                "user_id": msg.user_id,
                "input_tokens": msg.input_tokens,
                "output_tokens": msg.output_tokens,
            }]
        }
        resp = httpx.post(
            f"{mb_url}/api/motherbrain/ingest",
            json=payload,
            headers={"Authorization": f"Bearer {mb_key}"},
            timeout=10.0,
        )
        if resp.status_code == 200:
            msg.synced_to_motherbrain = True
            db.commit()
            print(f"[Telemetry] Pushed message_id={message_id} to Motherbrain")
        else:
            print(f"[Telemetry] Motherbrain rejected message_id={message_id}: {resp.status_code}")
    except Exception as e:
        print(f"[Telemetry] Push to Motherbrain failed for message_id={message_id}: {e}")
    finally:
        db.close()


@app.post("/api/conversations/feedback")
def submit_feedback(request: FeedbackRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    msg = db.query(ConversationMessage).filter(ConversationMessage.id == request.message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    msg.user_feedback = request.feedback
    if request.comment:
        msg.feedback_comment = request.comment
    db.commit()

    # On negative feedback — auto extract context + push to Motherbrain
    if request.feedback == -1:
        conv = db.query(Conversation).filter(Conversation.id == msg.conversation_id).first()
        client_id = conv.client_id if conv else _normalize_client_id(None)
        if request.comment and len(request.comment.strip()) > 10:
            background_tasks.add_task(
                _run_auto_extract_override,
                client_id,
                msg.id,
                msg.user_prompt or "",
                request.comment,
            )
        background_tasks.add_task(_push_telemetry_to_motherbrain, msg.id, force=True)

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
    app_name: Optional[str] = None
    description: Optional[str] = None

@app.post("/api/context-overrides")
def create_context_override(request: ContextOverrideRequest, db: Session = Depends(get_db)):
    from database import ClientContextOverride
    try:
        new_override = ClientContextOverride(
            client_id=request.client_id,
            term=request.term,
            sql_logic=request.sql_logic,
            app_name=request.app_name,
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
def get_context_overrides(client_id: str, app_name: Optional[str] = None, db: Session = Depends(get_db)):
    from database import ClientContextOverride
    query = db.query(ClientContextOverride).filter(ClientContextOverride.client_id == client_id)
    if app_name:
        from sqlalchemy import or_
        query = query.filter(or_(ClientContextOverride.app_name == app_name, ClientContextOverride.app_name == None))
    
    overrides = query.order_by(ClientContextOverride.created_at.desc()).all()
    return [
        {
            "id": r.id,
            "term": r.term,
            "sql_logic": r.sql_logic,
            "app_name": r.app_name,
            "description": r.description
        }
        for r in overrides
    ]

# --- Dynamic Learning Management Endpoints ---

class SystemPromptRequest(BaseModel):
    client_id: str
    segment_key: str
    prompt_text: str
    app_name: Optional[str] = None
    is_active: bool = True

@app.post("/api/system-prompts")
def create_system_prompt(request: SystemPromptRequest, db: Session = Depends(get_db)):
    from database import ClientSystemPrompt
    try:
        new_prompt = ClientSystemPrompt(
            client_id=request.client_id,
            app_name=request.app_name,
            segment_key=request.segment_key,
            prompt_text=request.prompt_text,
            is_active=request.is_active
        )
        db.add(new_prompt)
        db.commit()
        db.refresh(new_prompt)
        return {"status": "success", "id": new_prompt.id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/system-prompts/{client_id}")
def get_system_prompts(client_id: str, app_name: Optional[str] = None, db: Session = Depends(get_db)):
    from database import ClientSystemPrompt
    query = db.query(ClientSystemPrompt).filter(ClientSystemPrompt.client_id == client_id)
    if app_name:
        from sqlalchemy import or_
        query = query.filter(or_(ClientSystemPrompt.app_name == app_name, ClientSystemPrompt.app_name == None))
    
    prompts = query.order_by(ClientSystemPrompt.created_at.desc()).all()
    return [
        {
            "id": p.id,
            "segment_key": p.segment_key,
            "prompt_text": p.prompt_text,
            "app_name": p.app_name,
            "is_active": p.is_active,
            "created_at": p.created_at.isoformat() if p.created_at else None
        }
        for p in prompts
    ]

@app.delete("/api/system-prompts/{prompt_id}")
def delete_system_prompt(prompt_id: int, db: Session = Depends(get_db)):
    from database import ClientSystemPrompt
    prompt = db.query(ClientSystemPrompt).filter(ClientSystemPrompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt segment not found")
    try:
        db.delete(prompt)
        db.commit()
        return {"status": "success"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

class FeatureFlagToggleRequest(BaseModel):
    client_id: str
    feature_key: str
    is_enabled: bool

@app.post("/api/feature-flags/toggle")
def toggle_feature_flag(request: FeatureFlagToggleRequest, db: Session = Depends(get_db)):
    from database import ClientFeatureFlag
    flag = db.query(ClientFeatureFlag).filter(
        ClientFeatureFlag.client_id == request.client_id,
        ClientFeatureFlag.feature_key == request.feature_key
    ).first()
    
    if flag:
        flag.is_enabled = request.is_enabled
    else:
        flag = ClientFeatureFlag(
            client_id=request.client_id,
            feature_key=request.feature_key,
            is_enabled=request.is_enabled
        )
        db.add(flag)
    
    db.commit()
    return {"status": "success", "feature_key": request.feature_key, "is_enabled": flag.is_enabled}

@app.get("/api/feature-flags/{client_id}")
def get_feature_flags(client_id: str, db: Session = Depends(get_db)):
    from database import ClientFeatureFlag
    flags = db.query(ClientFeatureFlag).filter(ClientFeatureFlag.client_id == client_id).all()
    return {f.feature_key: f.is_enabled for f in flags}

# --- Conversation History Endpoints ---

@app.get("/api/conversations/{client_id}")
def get_conversations(client_id: str, user_id: Optional[str] = None, db: Session = Depends(get_db)):
    """Fetch all conversation heads for a specific client and user."""
    normalized_client_id = _normalize_client_id(client_id).strip()
    
    # Using correlated subqueries for title and last_message_at
    title_subquery = (
        db.query(ConversationMessage.user_prompt)
        .filter(ConversationMessage.conversation_id == Conversation.id)
        .order_by(ConversationMessage.created_at.asc(), ConversationMessage.id.asc())
        .limit(1)
        .correlate(Conversation)
        .as_scalar()
    )
    
    last_message_at_subquery = (
        db.query(func.max(ConversationMessage.created_at))
        .filter(ConversationMessage.conversation_id == Conversation.id)
        .correlate(Conversation)
        .as_scalar()
    )
    
    last_activity_expr = func.coalesce(last_message_at_subquery, Conversation.created_at)
    
    query = db.query(
        Conversation.id,
        Conversation.app_name,
        Conversation.created_at,
        title_subquery.label("title")
    ).filter(func.trim(Conversation.client_id) == normalized_client_id)
    
    if user_id:
        query = query.filter(Conversation.user_id == user_id)
    last_activity_expr = func.coalesce(last_message_at_subquery, Conversation.created_at)
    
    convs = query.order_by(last_activity_expr.desc(), Conversation.id.desc()).all()

    return [
        {
            "id": c.id,
            "app_name": c.app_name,
            "title": c.title or "New Conversation",
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in convs
    ]

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
    client_id: Optional[str] = "DEMO_CLIENT_123"

@app.post("/api/execute-sql")
async def api_execute_sql(request: ExecuteSqlRequest):
    """Securely re-execute a historical SQL query."""
    try:
        validated_sql = validate_sql(request.sql)
        data = await run_query(validated_sql, client_id=request.client_id)
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


# ---------------------------------------------------------------------------
# Pending Context Overrides (auto-extracted, awaiting admin approval)
# ---------------------------------------------------------------------------

@app.get("/api/pending-overrides/{client_id}")
def get_pending_overrides(client_id: str, db: Session = Depends(get_db)):
    from database import PendingContextOverride
    items = (
        db.query(PendingContextOverride)
        .filter(
            PendingContextOverride.client_id == client_id,
            PendingContextOverride.status == "pending",
        )
        .order_by(PendingContextOverride.created_at.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "client_id": r.client_id,
            "source_message_id": r.source_message_id,
            "original_prompt": r.original_prompt,
            "feedback_comment": r.feedback_comment,
            "term": r.term,
            "sql_logic": r.sql_logic,
            "description": r.description,
            "confidence": r.confidence,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in items
    ]


@app.post("/api/pending-overrides/{pending_id}/approve")
def approve_pending_override(pending_id: int, db: Session = Depends(get_db)):
    """Promote a pending override to an active ClientContextOverride."""
    from database import PendingContextOverride, ClientContextOverride
    pending = db.query(PendingContextOverride).filter(PendingContextOverride.id == pending_id).first()
    if not pending:
        raise HTTPException(status_code=404, detail="Pending override not found")
    try:
        new_override = ClientContextOverride(
            client_id=pending.client_id,
            term=pending.term,
            sql_logic=pending.sql_logic,
            description=pending.description,
        )
        db.add(new_override)
        pending.status = "approved"
        db.commit()
        db.refresh(new_override)
        return {"status": "approved", "override_id": new_override.id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/pending-overrides/{pending_id}/reject")
def reject_pending_override(pending_id: int, db: Session = Depends(get_db)):
    """Reject a pending auto-extracted override."""
    from database import PendingContextOverride
    pending = db.query(PendingContextOverride).filter(PendingContextOverride.id == pending_id).first()
    if not pending:
        raise HTTPException(status_code=404, detail="Pending override not found")
    try:
        pending.status = "rejected"
        db.commit()
        return {"status": "rejected"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Context Health — per-client AI learning summary
# ---------------------------------------------------------------------------

@app.get("/api/context-health/{client_id}")
def get_context_health(client_id: str, db: Session = Depends(get_db)):
    """
    Returns a summary of how much the AI has learned about a specific client.
    Useful for the Motherbrain admin dashboard.
    """
    from database import ClientContextOverride, PendingContextOverride
    normalized = _normalize_client_id(client_id)

    saved_reports = db.query(SavedReport).filter(SavedReport.client_id == normalized).count()

    success_msgs = (
        db.query(ConversationMessage)
        .join(Conversation)
        .filter(
            Conversation.client_id == normalized,
            ConversationMessage.execution_status == "success",
        )
        .count()
    )

    context_overrides = (
        db.query(ClientContextOverride)
        .filter(ClientContextOverride.client_id == normalized)
        .count()
    )

    pending_overrides = (
        db.query(PendingContextOverride)
        .filter(
            PendingContextOverride.client_id == normalized,
            PendingContextOverride.status == "pending",
        )
        .count()
    )

    # Embedding coverage over successful messages
    total_msgs = (
        db.query(ConversationMessage)
        .join(Conversation)
        .filter(Conversation.client_id == normalized)
        .count()
    )
    embedded_msgs = (
        db.query(ConversationMessage)
        .join(Conversation)
        .filter(
            Conversation.client_id == normalized,
            ConversationMessage.embedding.isnot(None),
        )
        .count()
    )
    embedding_pct = round((embedded_msgs / total_msgs) * 100) if total_msgs > 0 else 0

    # Last learning event (most recent approved override or successful message)
    last_override = (
        db.query(ClientContextOverride)
        .filter(ClientContextOverride.client_id == normalized)
        .order_by(ClientContextOverride.created_at.desc())
        .first()
    )
    last_success = (
        db.query(ConversationMessage)
        .join(Conversation)
        .filter(
            Conversation.client_id == normalized,
            ConversationMessage.execution_status == "success",
        )
        .order_by(ConversationMessage.created_at.desc())
        .first()
    )
    candidates = [x.created_at for x in [last_override, last_success] if x and x.created_at]
    last_learning = max(candidates).isoformat() if candidates else None

    return {
        "client_id": normalized,
        "saved_reports": saved_reports,
        "successful_conversations": success_msgs,
        "context_overrides": context_overrides,
        "pending_overrides": pending_overrides,
        "embedding_coverage_pct": embedding_pct,
        "last_learning_event": last_learning,
    }
