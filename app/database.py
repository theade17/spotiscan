from sqlmodel import SQLModel, create_engine, Session
from .models import *
import os

sqlite_file_name = "titlescan.db"
database_url = os.getenv("DATABASE_URL", f"sqlite:///{sqlite_file_name}")

# Render gives URLs starting with postgres:// but SQLAlchemy requires postgresql://
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

engine = create_engine(database_url, echo=True)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session
