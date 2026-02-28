from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from ai_engine import generate_sql
from sql_validator import validate_sql
from erp_client import run_query

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def home():
    return {"message": "ERP AI Backend is running"}
    
from typing import List, Optional, Dict
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