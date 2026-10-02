from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from backend.config import ensure_directories,settings
from backend.database.db import init_db
from backend.routes import projects, documentation_chat
@asynccontextmanager
async def lifespan(app): ensure_directories(); init_db(); yield
app=FastAPI(title=settings.APP_NAME,version=settings.APP_VERSION,description='Evidence-based documentation generation and maintenance assistant.',lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=[x.strip() for x in settings.CORS_ORIGINS.split(',') if x.strip()],allow_credentials=True,allow_methods=['GET','POST','DELETE'],allow_headers=['*'])
app.include_router(projects.router)
app.include_router(documentation_chat.router)
FRONTEND_DIR=Path(__file__).resolve().parent.parent/'frontend'; app.mount('/static',StaticFiles(directory=str(FRONTEND_DIR)),name='static')
@app.get('/api/health')
def health(): return {'status':'healthy','app_name':settings.APP_NAME,'version':settings.APP_VERSION,'gemini_configured':bool(settings.GEMINI_API_KEY)}
@app.get('/')
def home(): return FileResponse(FRONTEND_DIR/'index.html')
@app.get('/upload')
def upload(): return FileResponse(FRONTEND_DIR/'upload.html')
@app.get('/documentation')
def docs(): return FileResponse(FRONTEND_DIR/'documentation.html')
@app.get('/history')
def history(): return FileResponse(FRONTEND_DIR/'history.html')
@app.get('/profile')
def profile(): return FileResponse(FRONTEND_DIR/'profile.html')
