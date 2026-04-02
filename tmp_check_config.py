import os
import json
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("DATABASE_URL not found in .env")
    exit(1)

engine = create_engine(DATABASE_URL)

def check_configs():
    print("\n--- Client Configs ---")
    with engine.connect() as conn:
        try:
            result = conn.execute(text("SELECT id, client_id, erp_url, app_name_override, is_active FROM client_configs"))
            cols = result.keys()
            rows = result.fetchall()
            for row in rows:
                print(dict(zip(cols, row)))
        except Exception as e:
            print(f"Error: {e}")

check_configs()
