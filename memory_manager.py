from difflib import SequenceMatcher
from database import SessionLocal, SavedReport

def get_relevant_schema_context(client_id: str, new_prompt: str, top_k: int = 3) -> str:
    """
    Fetches the most relevant previously saved reports for the given client
    based on a simple string similarity ratio between the new prompt and historical prompts.
    """
    db = SessionLocal()
    try:
        # Fetch all saved reports for this client
        reports = db.query(SavedReport).filter(SavedReport.client_id == client_id).all()
        if not reports:
            return ""

        # Score reports based on string similarity
        scored_reports = []
        for report in reports:
            # Calculate similarity ratio (0.0 to 1.0)
            ratio = SequenceMatcher(None, new_prompt.lower(), report.original_prompt.lower()).ratio()
            scored_reports.append((ratio, report))
        
        # Sort by highest similarity descending
        scored_reports.sort(key=lambda x: x[0], reverse=True)
        
        # Take the top_k matches that have at least some similarity (> 0.1)
        best_matches = [r for score, r in scored_reports if score > 0.1][:top_k]
        
        if not best_matches:
            return ""
            
        context_lines = [
            "### PREVIOUSLY SUCCESSFUL CLIENT QUERIES ###",
            "The following are examples of how EXACTLY to format the SQL for this specific client based on their past successful queries. USE THESE AS YOUR BLUEPRINT for table joins, column names, and formula logic:",
            ""
        ]
        
        for r in best_matches:
            context_lines.append(f"-- User Asked: {r.original_prompt}")
            context_lines.append(f"-- Correct SQL Used:")
            context_lines.append(f"{r.sql_query}")
            context_lines.append("")
            
        return "\n".join(context_lines)
    finally:
        db.close()
