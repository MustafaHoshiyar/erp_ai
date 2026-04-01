from database import SessionLocal, ClientConfig, init_db, engine
from sqlalchemy import text

def apply_currency():
    # 1. Force Run Migrations
    print("Checking database migrations...")
    init_db(engine)
    
    db = SessionLocal()
    try:
        # 2. Update Eagle Group
        eagle = db.query(ClientConfig).filter(ClientConfig.client_id == 'eagle_group').first()
        if eagle:
            eagle.default_currency_code = "KWD"
            eagle.default_currency_symbol = "KWD"
            print(f"Set Eagle Group Currency to: {eagle.default_currency_code}")
            
        # 3. Update Supernatural
        supernat = db.query(ClientConfig).filter(ClientConfig.client_id == 'supernatural').first()
        if supernat:
            supernat.default_currency_code = "KWD"
            supernat.default_currency_symbol = "KWD"
            print(f"Set Supernatural Currency to: {supernat.default_currency_code}")
            
        db.commit()
    except Exception as e:
        print(f"Error seeding currency: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    apply_currency()
