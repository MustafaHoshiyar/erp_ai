import json
import os

TOKEN_FILE = "token_usage.json"
TOKEN_LIMIT = 100000

def get_token_usage():
    if not os.path.exists(TOKEN_FILE):
        return {"used": 0, "limit": TOKEN_LIMIT}
    
    try:
        with open(TOKEN_FILE, "r") as f:
            data = json.load(f)
            return {"used": data.get("used", 0), "limit": TOKEN_LIMIT}
    except Exception:
        return {"used": 0, "limit": TOKEN_LIMIT}

def add_tokens(amount):
    if not amount:
        return
        
    current = get_token_usage()
    current["used"] += amount
    
    with open(TOKEN_FILE, "w") as f:
        json.dump(current, f)
