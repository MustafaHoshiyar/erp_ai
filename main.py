from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from ai_engine import generate_sql, generate_chart_config
from sql_validator import validate_sql
from erp_client import run_query

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def home():
    return {"message": "ERP AI Backend is running"}
    
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

class PromptRequest(BaseModel):
    prompt: str
    history: Optional[List[Dict[str, str]]] = None

@app.post("/generate-report")
async def generate_report(request: PromptRequest):
    result = generate_sql(request.prompt, request.history)

    # If no SQL was generated, just return the conversational message
    if not result.get("sql"):
        return {
            "sql": None,
            "data": None,
            "message": result.get("message")
        }

    validated_sql = validate_sql(result["sql"])
    data = await run_query(validated_sql)

    return {
        "sql": validated_sql,
        "data": data,
        "message": result.get("message")
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
