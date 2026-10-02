from logging.config import fileConfig
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import engine_from_config,pool
from alembic import context
from backend.database.models import Base
from backend.config import settings
config=context.config
config.set_main_option('sqlalchemy.url',settings.DATABASE_URL)
# Logging configuration is optional for this minimal deployment.
target_metadata=Base.metadata
def run_migrations_offline(): context.configure(url=settings.DATABASE_URL,target_metadata=target_metadata,literal_binds=True); context.run_migrations()
def run_migrations_online():
    with engine_from_config(config.get_section(config.config_ini_section),prefix='sqlalchemy.',poolclass=pool.NullPool).connect() as c: context.configure(connection=c,target_metadata=target_metadata); context.run_migrations()
(run_migrations_offline if context.is_offline_mode() else run_migrations_online)()
