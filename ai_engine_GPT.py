import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """
You are an AI assistant for an ERPNext platform.
Your job is to either have a normal conversation with the user OR generate a SQL query to fetch data if they ask for it.

Important ERPNext tables:
- `tabSales Invoice`
- `tabSales Invoice Item`
- `tabItem`
- `tabStock Ledger Entry`
- `tabWarehouse`

Rules for SQL:
- Only generate SELECT queries.
- Never use DELETE, UPDATE, DROP, INSERT, ALTER.
- Always include LIMIT 500.
- Use ERPNext table names prefixed with `tab`.
- IF YOU ARE GENERATING SQL, YOU MUST WRAP IT EXACTLY IN ```sql AND ```. DO NOT RETURN RAW SQL WITHOUT THE MARKDOWN BLOCK.

Rules for Conversation:
- If the user says "hello" or asks a general question, just reply nicely as an AI assistant. DO NOT GENERATE SQL.
"""

def generate_sql(user_prompt):
    response = client.chat.completions.create(
        model=os.getenv("AI_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0
    )

    raw_output = response.choices[0].message.content.strip()
    tokens_used = response.usage.total_tokens if hasattr(response, "usage") and response.usage else 0

    import re
    # Try to extract SQL from a markdown block
    match = re.search(r"```sql(.*?)```", raw_output, re.IGNORECASE | re.DOTALL)
    if match:
        return {"sql": match.group(1).strip(), "message": raw_output, "tokens_used": tokens_used}

    # Fallback
    match = re.search(r"(SELECT .*?;)", raw_output, re.IGNORECASE | re.DOTALL)
    if match:
        return {"sql": match.group(1).strip(), "message": raw_output, "tokens_used": tokens_used}

    # Fallback if no semicolon
    match = re.search(r"(SELECT .*?$)", raw_output, re.IGNORECASE | re.DOTALL)
    if match:
        return {"sql": match.group(1).strip(), "message": raw_output, "tokens_used": tokens_used}

    # Conversational reply, no SQL
    return {"sql": None, "message": raw_output, "tokens_used": tokens_used}