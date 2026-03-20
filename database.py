import os
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, JSON, ForeignKey, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.sql import func
from dotenv import load_dotenv

load_dotenv()

# Determine database URL. For simplicity in Phase 2, we default to SQLite.
# This will create a file named 'erp_ai_memory.db' in the project root.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./erp_ai_memory.db")

engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
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
    name = Column(String(255), index=True)     # User-given name for the report
    original_prompt = Column(Text)
    sql_query = Column(Text, nullable=False)
    chart_config = Column(JSON, nullable=True) # Stores Chart.js configuration
    embedding = Column(JSON, nullable=True)    # Stores specific float array for semantic search
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# Create all tables in the engine
Base.metadata.create_all(bind=engine)

class Conversation(Base):
    __tablename__ = "conversations"
    
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(String(50), index=True)
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
    term = Column(String(100), index=True) # e.g., "Revenue"
    sql_logic = Column(Text)               # e.g., "SUM(tabSales Invoice.grand_total)"
    description = Column(Text, nullable=True) # e.g., "Client A defines revenue as invoiced amount"
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# Re-run create_all in case new tables were added (SQLite safe if tables don't exist)
Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
