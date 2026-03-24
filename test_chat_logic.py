import asyncio
from ai_engine import classify_prompt_intent, generate_chat_response

history = [
    {"role": "user", "content": "most profitable item"},
    {"role": "assistant", "content": "SELECT item_code, sum(net_amount) AS profit FROM `tabSales Invoice Item` GROUP BY item_code ORDER BY profit DESC LIMIT 1"}
]

prompt = "what was your logic behind this result"

print("Intent:", classify_prompt_intent(prompt, history).get("intent"))

result = generate_chat_response(prompt, history)
print("Response SQL:", result.get("sql"))
print("Response MSG:", result.get("message"))
print("Detected Intent:", result.get("detected_intent", "MISSING"))
