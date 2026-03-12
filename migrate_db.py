import sqlite3
import os

DATABASE_PATH = "erp_ai_memory.db"

def migrate():
    if not os.path.exists(DATABASE_PATH):
        print(f"Database {DATABASE_PATH} not found. Skipping migration (it will be created fresh).")
        return

    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    # Get existing columns in conversation_messages
    cursor.execute("PRAGMA table_info(conversation_messages)")
    conv_msg_columns = [row[1] for row in cursor.fetchall()]

    # Get existing columns in conversations
    cursor.execute("PRAGMA table_info(conversations)")
    conv_columns = [row[1] for row in cursor.fetchall()]

    if "app_name" not in conv_columns:
        print("Adding 'app_name' column to 'conversations' table...")
        try:
            cursor.execute("ALTER TABLE conversations ADD COLUMN app_name TEXT")
            conn.commit()
            print("Successfully added 'app_name' column.")
        except Exception as e:
            print(f"Error adding app_name to conversations: {e}")

    if "feedback_comment" not in conv_msg_columns:
        print("Adding 'feedback_comment' column to 'conversation_messages' table...")
        try:
            cursor.execute("ALTER TABLE conversation_messages ADD COLUMN feedback_comment TEXT")
            conn.commit()
            print("Successfully added 'feedback_comment' column.")
        except Exception as e:
            print(f"Error adding column: {e}")
    else:
        print("'feedback_comment' column already exists.")

    # Check for other columns if they might be missing too (from recent phases)
    missing_cols = {
        "tokens_used": "INTEGER",
        "embedding": "JSON"
    }
    
    for col, dtype in missing_cols.items():
        if col not in conv_msg_columns:
            print(f"Adding '{col}' column to 'conversation_messages' table...")
            try:
                cursor.execute(f"ALTER TABLE conversation_messages ADD COLUMN {col} {dtype}")
                conn.commit()
                print(f"Successfully added '{col}' column.")
            except Exception as e:
                print(f"Error adding {col}: {e}")

    conn.close()
    print("Migration check complete.")

if __name__ == "__main__":
    migrate()
