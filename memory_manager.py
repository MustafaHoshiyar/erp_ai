import math
import os
from openai import OpenAI
from dotenv import load_dotenv
from database import SessionLocal, SavedReport, Conversation, ConversationMessage

load_dotenv()
openai_api_key = os.getenv("OPENAI_API_KEY")
embedding_client = OpenAI(api_key=openai_api_key) if openai_api_key else None

def get_embedding(text: str) -> list[float]:
    if not embedding_client:
        return []
    try:
        response = embedding_client.embeddings.create(
            input=text,
            model="text-embedding-3-small"
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"[MemoryManager] Error getting embedding: {e}")
        return []

def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm_a = math.sqrt(sum(a * a for a in vec1))
    norm_b = math.sqrt(sum(b * b for b in vec2))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product / (norm_a * norm_b)

def get_relevant_schema_context(client_id: str, new_prompt: str, top_k: int = 3) -> str:
    db = SessionLocal()
    try:
        reports = db.query(SavedReport).filter(SavedReport.client_id == client_id).all()
        
        success_msgs = db.query(ConversationMessage).join(Conversation).filter(
            Conversation.client_id == client_id,
            ConversationMessage.execution_status == "success"
        ).all()
        success_msgs = [m for m in success_msgs if m.user_feedback != -1]
        
        all_past_queries = list(reports) + success_msgs
            
        if not all_past_queries:
            return ""

        query_embedding = get_embedding(new_prompt)
        if not query_embedding:
            return ""

        scored_records = []
        for record in all_past_queries:
            if not record.embedding:
                text_to_embed = record.original_prompt if hasattr(record, 'original_prompt') else record.user_prompt
                emb = get_embedding(text_to_embed)
                if emb:
                    record.embedding = emb
                    db.commit()
            
            if record.embedding:
                sim = cosine_similarity(query_embedding, record.embedding)
                scored_records.append((sim, record))
                
        scored_records.sort(key=lambda x: x[0], reverse=True)
        # Threshold for semantic similarity, e.g., > 0.4
        best_matches = [r for score, r in scored_records if score > 0.4][:top_k]
        
        if not best_matches:
            return ""
            
        context_lines = [
            "### PREVIOUSLY SUCCESSFUL CLIENT QUERIES ###",
            "The following are examples of how EXACTLY to format the SQL for this specific client based on their past successful queries. USE THESE AS YOUR BLUEPRINT for table joins, column names, and formula logic:",
            ""
        ]
        
        for r in best_matches:
            prompt = r.original_prompt if hasattr(r, 'original_prompt') else r.user_prompt
            sql = r.sql_query if hasattr(r, 'sql_query') else r.generated_sql
            context_lines.append(f"-- User Asked: {prompt}")
            context_lines.append(f"-- Correct SQL Used:")
            context_lines.append(f"{sql}")
            context_lines.append("")
            
        return "\n".join(context_lines)
    finally:
        db.close()
