import os
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, JSON
from sqlalchemy.orm import declarative_base, sessionmaker
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
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# Create all tables in the engine
Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
