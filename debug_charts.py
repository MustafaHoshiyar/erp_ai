import os
import json
import httpx
from dotenv import load_dotenv

load_dotenv()

ERP_URL = os.getenv("ERP_URL")
ERP_API_KEY = os.getenv("ERP_API_KEY")
ERP_API_SECRET = os.getenv("ERP_API_SECRET")

headers = {
    "Authorization": f"token {ERP_API_KEY}:{ERP_API_SECRET}",
    "Content-Type": "application/json"
}

def print_json(data):
    try:
        if isinstance(data, str):
            parsed = json.loads(data)
            print(json.dumps(parsed, indent=2))
        else:
            print(json.dumps(data, indent=2))
    except (json.JSONDecodeError, TypeError):
        print(data)

def run():
    print(f"Fetching from {ERP_URL}...")
    
    script = """
import frappe
import json

charts = frappe.db.sql("SELECT name, title, chart_type, operations FROM `tabInsights Chart v3` ORDER BY creation DESC LIMIT 5", as_dict=True)
for c in charts:
    if c.get("operations"):
        try:
            c["operations"] = json.loads(c["operations"])
        except:
            pass

dashboards = frappe.db.sql("SELECT name, title, items FROM `tabInsights Dashboard v3` ORDER BY creation DESC LIMIT 3", as_dict=True)
for d in dashboards:
    if d.get("items"):
        try:
            d["items"] = json.loads(d["items"])
        except:
            pass

frappe.response["message"] = {
    "charts": charts,
    "dashboards": dashboards
}
"""

    r = httpx.post(
        f"{ERP_URL}/api/method/frappe.client.execute",
        headers=headers,
        json={"cmd": "frappe.client.execute", "script": script}
    )
    
    if r.status_code == 200:
        data = r.json().get("message", {})
        
        print("\n=== RECENT CHARTS ===")
        for c in data.get("charts", []):
            print(f"-- Chart: {c['title']} ({c['name']} | Type: {c['chart_type']}) --")
            print_json(c['operations'])
            
        print("\n=== RECENT DASHBOARDS ===")
        for d in data.get("dashboards", []):
            print(f"-- Dashboard: {d['title']} ({d['name']}) --")
            print_json(d['items'])
    else:
        print(f"Error {r.status_code}: {r.text}")

if __name__ == "__main__":
    run()
