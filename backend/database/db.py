from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.config import ensure_directories, settings
from backend.database.models import Base
ensure_directories()
engine=create_engine(settings.DATABASE_URL, connect_args={'check_same_thread':False}, echo=False)
SessionLocal=sessionmaker(autocommit=False, autoflush=False, bind=engine)
def init_db(): Base.metadata.create_all(bind=engine)
def get_db():
    db=SessionLocal()
    try: yield db
    finally: db.close()
