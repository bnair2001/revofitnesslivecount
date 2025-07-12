import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/revo")

engine = create_engine(DB_URL, pool_pre_ping=True)
Session = scoped_session(sessionmaker(bind=engine))
