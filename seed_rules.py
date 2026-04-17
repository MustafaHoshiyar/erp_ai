import os
import sys
import argparse

# Add the project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal, ClientSystemPrompt, ClientFeatureFlag, ClientContextOverride

def seed_database():
    db = SessionLocal()
    try:
        # 1. Provide initial global feature flags
        flags = [
            ("strict_date_filtering", True),
            ("sales_invoice_followup_guardrail", True),
            ("high_density_mode", False),
        ]
        
        added_flags = 0
        for key, enabled in flags:
            existing = db.query(ClientFeatureFlag).filter_by(client_id="GLOBAL", feature_key=key).first()
            if not existing:
                db.add(ClientFeatureFlag(client_id="GLOBAL", feature_key=key, is_enabled=enabled))
                added_flags += 1

        # 2. Add System Prompt segments based on previous hardcoded logic
        system_prompts = [
            {
                "segment_key": "maintenance_rules",
                "prompt_text": "When the user asks about Maintenance or Maintenance Visits, prefer querying the 'tabMaintenance' doctype over 'tabMaintenance Schedule' unless explicitly requested."
            },
            {
                "segment_key": "sales_invoice_rules",
                "prompt_text": "When fetching sales or revenue aggregates from 'tabSales Invoice', always filter by is_return = 0 unless the user specifically asks for returns or canceled invoices."
            }
        ]
        
        added_prompts = 0
        for sp in system_prompts:
            existing = db.query(ClientSystemPrompt).filter_by(client_id="GLOBAL", segment_key=sp["segment_key"]).first()
            if not existing:
                db.add(ClientSystemPrompt(
                    client_id="GLOBAL",
                    segment_key=sp["segment_key"],
                    prompt_text=sp["prompt_text"]
                ))
                added_prompts += 1

        # 3. Add Context Overrides (Examples of semantic term mappings)
        overrides = [
            {
                "term": "Net Revenue",
                "sql_logic": "SUM(grand_total) - SUM(discount_amount)",
                "description": "Standard business definition for net revenue across all modules."
            }
        ]
        
        added_overrides = 0
        for ov in overrides:
            existing = db.query(ClientContextOverride).filter_by(client_id="GLOBAL", term=ov["term"]).first()
            if not existing:
                db.add(ClientContextOverride(
                    client_id="GLOBAL",
                    term=ov["term"],
                    sql_logic=ov["sql_logic"],
                    description=ov["description"]
                ))
                added_overrides += 1

        db.commit()
        print(f"Migration Complete: added {added_flags} flags, {added_prompts} system prompt rules, and {added_overrides} semantic overrides to PostgreSQL!")
    except Exception as e:
        db.rollback()
        print(f"Error during seeding: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed_database()
