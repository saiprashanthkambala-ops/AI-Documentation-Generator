"""Safe application configuration loaded from .env."""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
BASE_DIR = Path(__file__).resolve().parent.parent
class Settings(BaseSettings):
    APP_NAME: str = "AI Documentation Assistant"
    APP_VERSION: str = "3.0.0"
    DEBUG: bool = False
    GEMINI_API_KEY: str = ""
    DATABASE_URL: str = f"sqlite:///{(BASE_DIR/'database'/'app.db').as_posix()}"
    DATABASE_DIR: Path = BASE_DIR/'database'; UPLOADS_DIR: Path = BASE_DIR/'uploads'; DOCS_DIR: Path = BASE_DIR/'docs'
    MAX_ZIP_SIZE_MB: int = 20; MAX_ZIP_FILES: int = 2000; MAX_EXTRACTED_SIZE_MB: int = 100; MAX_CONTEXT_CHARS: int = 30000; MAX_LINES_PER_FILE: int = 160
    CORS_ORIGINS: str = "http://localhost:8000,http://127.0.0.1:8000"
    SOURCE_EXTENSIONS: set[str] = {'.py','.md','.txt','.json','.yaml','.yml','.toml','.cfg','.ini','.html','.css','.js','.ts','.tsx','.jsx'}
    SKIP_FOLDERS: set[str] = {'__pycache__','.git','.venv','venv','node_modules','.idea','.vscode','dist','build','.pytest_cache'}
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')
settings = Settings()
def ensure_directories():
    for path in (settings.DATABASE_DIR, settings.UPLOADS_DIR, settings.DOCS_DIR): path.mkdir(parents=True, exist_ok=True)
