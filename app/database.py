"""
Database connection and session management
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Database file path
DB_FILE = os.getenv('DB_FILE', 'data/apigeo.db')
DATABASE_URL = f'sqlite:///{DB_FILE}'

engine = create_engine(
    DATABASE_URL,
    connect_args={'check_same_thread': False},
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dependency to get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
