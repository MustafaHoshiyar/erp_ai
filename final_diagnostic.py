import os
import httpx
import psycopg
from dotenv import load_dotenv

load_dotenv()

def check_db():
    print("--- Database Health (Postgres) ---")
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("FAIL: DATABASE_URL not found in .env")
        return
    
    # Simple fix for postgresql+psycopg schema if using direct psycopg
    clean_url = db_url.replace("postgresql+psycopg://", "postgresql://")
    
    try:
        conn = psycopg.connect(clean_url, timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT version();")
        print(f"SUCCESS: Connected to PG. Version: {cur.fetchone()[0][:30]}...")
        conn.close()
    except Exception as e:
        print(f"FAIL: Database connection failed: {e}")

def check_erp():
    print("\n--- ERPNext Connectivity ---")
    erp_url = "https://supernatural.ribox.me"
    print(f"Attempting to reach: {erp_url}")
    
    try:
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            resp = client.get(f"{erp_url}/api/method/ping", verify=False)
            print(f"STATUS: {resp.status_code}")
            print(f"BODY: {resp.text[:50]}")
            if resp.status_code == 200:
                print("SUCCESS: ERPNext server is reachable.")
            else:
                print("WARN: ERPNext reachable but returned error status.")
    except Exception as e:
        print(f"FAIL: Could not reach ERPNext: {e}")

def check_motherbrain():
    print("\n--- Motherbrain API Health ---")
    mb_url = os.getenv("MOTHERBRAIN_URL", "http://admin.ribox.me")
    print(f"Targeting Motherbrain at: {mb_url}")
    
    try:
        with httpx.Client(timeout=5) as client:
            resp = client.get(f"{mb_url}/health")
            print(f"STATUS: {resp.status_code}")
            if resp.status_code == 200:
                print("SUCCESS: Motherbrain API is healthy.")
            else:
                print("WARN: Motherbrain returned non-200 status.")
    except Exception as e:
        print(f"FAIL: Could not reach Motherbrain: {e}")

if __name__ == "__main__":
    check_db()
    check_erp()
    check_motherbrain()
