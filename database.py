import os

from dotenv import load_dotenv
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, create_engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.sql import func

load_dotenv(override=True)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./erp_ai_memory.db")
IS_SQLITE = DATABASE_URL.startswith("sqlite")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if IS_SQLITE else {},
    pool_pre_ping=not IS_SQLITE,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class GlobalQuery(Base):
    __tablename__ = "global_queries"
    
    id = Column(Integer, primary_key=True, index=True)
    prompt = Column(Text, index=True)
    sql_query = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # In a full pgvector implementation, we would add an embedding column here:
    # embedding = Column(Vector(1536))

class SavedReport(Base):
    __tablename__ = "saved_reports"
    
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(String(50), index=True) # Identifier for the specific client/user
    user_id = Column(String(100), index=True, nullable=True) # User-level isolation
    name = Column(String(255), index=True)     # User-given name for the report
    original_prompt = Column(Text)
    sql_query = Column(Text, nullable=False)
    chart_config = Column(JSON, nullable=True) # Stores Chart.js configuration
    embedding = Column(JSON, nullable=True)    # Stores specific float array for semantic search
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Conversation(Base):
    __tablename__ = "conversations"
    
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(String(50), index=True)
    user_id = Column(String(100), index=True, nullable=True) # User-level isolation
    app_name = Column(String(100), index=True, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    messages = relationship("ConversationMessage", back_populates="conversation", cascade="all, delete-orphan")

class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), index=True)
    user_prompt = Column(Text, nullable=False)
    detected_intent = Column(String(50), nullable=True)
    assistant_response = Column(Text, nullable=True)
    generated_sql = Column(Text, nullable=True)
    execution_status = Column(String(50), nullable=True) # "success", "error"
    error_message = Column(Text, nullable=True)
    user_feedback = Column(Integer, nullable=True) # 1 (positive), -1 (negative), etc.
    feedback_comment = Column(Text, nullable=True) # User's correction context
    tokens_used = Column(Integer, nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    user_id = Column(String(100), nullable=True)
    model_used = Column(String(100), nullable=True)
    routing_tables = Column(JSON, nullable=True)
    generation_ms = Column(Integer, nullable=True)
    execution_ms = Column(Integer, nullable=True)
    total_duration_ms = Column(Integer, nullable=True)
    embedding = Column(JSON, nullable=True)    # Stores specific float array for semantic search
    synced_to_motherbrain = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    conversation = relationship("Conversation", back_populates="messages")

class ClientContextOverride(Base):
    __tablename__ = "client_context_overrides"
    
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(String(50), index=True)
    app_name = Column(String(100), index=True, nullable=True) # Optional: filter by app context
    term = Column(String(100), index=True) # e.g., "Revenue"
    sql_logic = Column(Text)               # e.g., "SUM(tabSales Invoice.grand_total)"
    description = Column(Text, nullable=True) # e.g., "Client A defines revenue as invoiced amount"
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ClientSystemPrompt(Base):
    """Stores dynamic system prompt segments per client and optional app context."""
    __tablename__ = "client_system_prompts"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(String(50), index=True, nullable=False)
    app_name = Column(String(100), index=True, nullable=True)
    segment_key = Column(String(100), index=True, nullable=False) # e.g., "date_logic", "module_rules"
    prompt_text = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ClientFeatureFlag(Base):
    """Replaces hardcoded feature flags/guardrails for specific clients."""
    __tablename__ = "client_feature_flags"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(String(50), index=True, nullable=False)
    feature_key = Column(String(100), index=True, nullable=False) # e.g., "sales_invoice_followup_guardrail"
    is_enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ClientConfig(Base):
    """Stores per-client UI and engine configurations like currency and symbols."""
    __tablename__ = "client_configs"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(String(50), index=True, nullable=False, unique=True)
    erp_url = Column(String(500), nullable=False) # e.g. https://supernatural.ribox.me
    api_key = Column(String(255), nullable=False)
    api_secret = Column(String(255), nullable=False)
    erp_type = Column(String(20), default="erpnext") # 'erpnext' or 'odoo'
    odoo_db = Column(String(100), nullable=True)     # Odoo requires a DB name
    app_name_override = Column(String(100), nullable=True)
    default_currency_code = Column(String(10), default="KWD")
    default_currency_symbol = Column(String(10), default="KWD")
    is_active = Column(Boolean, default=True, nullable=False)

class PendingContextOverride(Base):
    """Auto-extracted context overrides from user feedback, pending admin review."""
    __tablename__ = "pending_context_overrides"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(String(50), index=True)
    source_message_id = Column(Integer, ForeignKey("conversation_messages.id"), nullable=True)
    original_prompt = Column(Text, nullable=True)  # The user's original query
    feedback_comment = Column(Text, nullable=True)  # What the user said was wrong
    term = Column(String(200), nullable=True)        # Extracted term
    sql_logic = Column(Text, nullable=True)          # Extracted SQL logic
    description = Column(Text, nullable=True)        # Human-readable description
    confidence = Column(Integer, nullable=True)      # 0–100 confidence score from AI
    status = Column(String(20), default="pending", index=True)  # pending, approved, rejected
    created_at = Column(DateTime(timezone=True), server_default=func.now())

from sqlalchemy import text, inspect

def init_db(bind_engine=None):
    target_engine = bind_engine or engine
    Base.metadata.create_all(bind=target_engine)
    
    # Auto-migration for missing columns
    try:
        inspector = inspect(target_engine)
        
        # New columns to add if they are missing
        migrations = {
            "conversation_messages": {
                "input_tokens": "INTEGER",
                "output_tokens": "INTEGER",
                "user_id": "TEXT",
                "model_used": "TEXT",
                "routing_tables": "JSON" if not IS_SQLITE else "TEXT",
                "generation_ms": "INTEGER",
                "execution_ms": "INTEGER",
                "total_duration_ms": "INTEGER",
                "synced_to_motherbrain": "BOOLEAN DEFAULT False"
            },
            "conversations": {
                "user_id": "VARCHAR(100)"
            },
            "saved_reports": {
                "user_id": "VARCHAR(100)"
            },
            "client_context_overrides": {
                "app_name": "VARCHAR(100)"
            },
            "client_configs": {
                "erp_type": "VARCHAR(20) DEFAULT 'erpnext'",
                "odoo_db": "VARCHAR(100)"
            }
        }
        
        with target_engine.begin() as conn:
            for table, columns_to_migrate in migrations.items():
                existing_cols = {col["name"] for col in inspector.get_columns(table)}
                for column, definition in columns_to_migrate.items():
                    if column not in existing_cols:
                        try:
                            # Standard SQL works for both PG and SQLite for simple ALTER
                            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
                            print(f"[{target_engine.name}] Migration: Added {column} to {table}")
                        except Exception as e:
                            print(f"[{target_engine.name}] Migration error for {table}.{column}: {e}")
    except Exception as outer_e:
        print(f"Database auto-migration safety check failed: {outer_e}")

init_db()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
