from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from ai_engine import generate_sql, generate_chart_config
from sql_validator import validate_sql
from erp_client import run_query
from database import SessionLocal, SavedReport, get_db
from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException

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
    
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

class PromptRequest(BaseModel):
    prompt: str
    history: Optional[List[Dict[str, str]]] = None
    client_id: Optional[str] = "DEMO_CLIENT_123"

@app.post("/generate-report")
async def generate_report(request: PromptRequest):
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

    # If no SQL was generated, just return the conversational message
    if not result.get("sql"):
        return {
            "sql": None,
            "data": None,
            "message": result.get("message"),
            "tokens_used": tokens_used
        }

    validated_sql = validate_sql(result["sql"])
    data = await run_query(validated_sql)

    return {
        "sql": validated_sql,
        "data": data,
        "message": result.get("message"),
        "tokens_used": tokens_used
    }

class ChartConfigRequest(BaseModel):
    columns: List[str]
    data_sample: List[Dict[str, Any]]

@app.post("/api/generate_chart_config")
async def api_generate_chart_config(request: ChartConfigRequest):
    try:
        config_str = generate_chart_config(request.columns, request.data_sample)
        import json
        config_json = json.loads(config_str)
        return config_json
    except Exception as e:
        return {"error": str(e)}

# --- Saved Reports Endpoints ---

class SaveReportRequest(BaseModel):
    client_id: str
    name: str
    original_prompt: str
    sql_query: str
    chart_config: Optional[Dict[str, Any]] = None

@app.post("/api/reports/save")
def save_report(request: SaveReportRequest, db: Session = Depends(get_db)):
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
        return {"status": "success", "id": new_report.id}
    except Exception as e:
        db.rollback()
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

