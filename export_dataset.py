import json
import argparse
from sqlalchemy.orm import Session
from database import SessionLocal, ConversationMessage, Conversation

def export_to_jsonl(output_file: str, only_successful: bool = True):
    db: Session = SessionLocal()
    
    query = db.query(ConversationMessage)
    if only_successful:
        query = query.filter(ConversationMessage.execution_status == "success")
        
    messages = query.all()
    
    export_count = 0
    with open(output_file, 'w', encoding='utf-8') as f:
        for msg in messages:
            # Format according to OpenAI fine-tuning JSONL format
            # We omit the massive system prompt here to keep the dataset size reasonable,
            # but ideally you'd include a base system prompt
            if msg.generated_sql:
                row = {
                    "messages": [
                        {"role": "system", "content": "You are a senior ERPNext database engineer and MariaDB expert. Generate accurate, optimized, production-ready ERPNext MariaDB queries using strict Frappe framework schema conventions."},
                        {"role": "user", "content": msg.user_prompt},
                        {"role": "assistant", "content": f"```sql\n{msg.generated_sql}\n```"}
                    ]
                }
                f.write(json.dumps(row) + "\n")
                export_count += 1
                
    db.close()
    print(f"Exported {export_count} messages to {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export conversation logs to JSONL for fine-tuning.")
    parser.add_argument("--output", "-o", default="dataset.jsonl", help="Output JSONL file path")
    parser.add_argument("--all", action="store_true", help="Export all messages, not just successful ones")
    
    args = parser.parse_args()
    export_to_jsonl(args.output, only_successful=not args.all)
