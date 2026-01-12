import os
import logging
import docker
import redis
import asyncio
from typing import List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# --- Configuration ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

POSTGRES_USER = os.getenv("POSTGRES_USER", "netadmin")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "netadmin_secret")
POSTGRES_DB = os.getenv("POSTGRES_DB", "netadmin_db")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "db")
DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}/{POSTGRES_DB}"

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")  # Simple MVP Auth

# --- Database ---
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class MonitoredTarget(Base):
    __tablename__ = "monitored_targets"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    hostname = Column(String)
    interval_seconds = Column(Integer, default=60)
    is_active = Column(Boolean, default=True)
    last_status = Column(String, nullable=True)
    last_check = Column(DateTime(timezone=True), nullable=True)

# Create tables (MVP approach - usually use migration tool)
Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Docker & Redis ---
docker_client = docker.from_env()
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

# --- FastAPI App ---
templates = Jinja2Templates(directory="src/templates")
app = FastAPI(title="NetAdmin Control Plane")

# Simple Auth Dependency
def verify_auth(request: Request):
    token = request.cookies.get("admin_token")
    if token != "valid_token": # Extremely simple MVP token
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("admin_token")
    if token != "valid_token":
        return templates.TemplateResponse("login.html", {"request": request})
    
    targets = db.query(MonitoredTarget).all()
    
    # Get Containers
    containers = []
    try:
        for c in docker_client.containers.list(all=True):
            # Filter only our stack if needed, or show all
            if "netadmin" in c.name or "redis" in c.name or "db" in c.name:
                containers.append({
                    "id": c.short_id,
                    "name": c.name,
                    "status": c.status,
                    "state": c.attrs['State']['Status']
                })
    except Exception as e:
        logger.error(f"Docker error: {e}")

    # Get Backups
    backups = []
    try:
        backup_dir = "/backups"
        if os.path.exists(backup_dir):
            for f in os.listdir(backup_dir):
                if f.endswith(".sql") or f.endswith(".tar.gz"):
                    path = os.path.join(backup_dir, f)
                    backups.append({
                        "name": f,
                        "size": f"{os.path.getsize(path) / 1024 / 1024:.2f} MB",
                        "created": os.path.getctime(path)
                    })
        backups.sort(key=lambda x: x['created'], reverse=True)
    except Exception as e:
        logger.error(f"Backup error: {e}")

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "targets": targets,
        "containers": containers,
        "backups": backups
    })

@app.post("/login")
async def login(password: str = Form(...)):
    if password == ADMIN_PASSWORD:
        response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(key="admin_token", value="valid_token")
        return response
    return RedirectResponse(url="/?error=Invalid Password", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("admin_token")
    return response

# --- Container Operations ---
@app.post("/api/containers/{container_id}/restart")
async def restart_container(container_id: str, _: None = Depends(verify_auth)):
    try:
        container = docker_client.containers.get(container_id)
        container.restart()
        return {"status": "success", "message": f"Container {container.name} restarting..."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/containers/{container_id}/logs")
async def get_logs(container_id: str, _: None = Depends(verify_auth)):
    try:
        container = docker_client.containers.get(container_id)
        # Get last 100 lines
        logs = container.logs(tail=100).decode('utf-8')
        return {"logs": logs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Target Operations ---
@app.post("/api/targets")
async def create_target(
    name: str = Form(...),
    hostname: str = Form(...),
    interval: int = Form(...),
    db: Session = Depends(get_db),
    _: None = Depends(verify_auth)
):
    target = MonitoredTarget(name=name, hostname=hostname, interval_seconds=interval)
    db.add(target)
    db.commit()
    
    # Notify Java Agent
    redis_client.publish("netadmin_events", "CONFIG_UPDATE:MONITORING")
    
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/api/targets/{target_id}/delete")
async def delete_target(target_id: int, db: Session = Depends(get_db), _: None = Depends(verify_auth)):
    db.query(MonitoredTarget).filter(MonitoredTarget.id == target_id).delete()
    db.commit()
    
    # Notify Java Agent
    redis_client.publish("netadmin_events", "CONFIG_UPDATE:MONITORING")
    
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

# --- Backup Operations ---
@app.get("/api/backups/download/{filename}")
async def download_backup(filename: str, _: None = Depends(verify_auth)):
    file_path = os.path.join("/backups", filename)
    # Basic path traversal protection
    if ".." in filename or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path, filename=filename)
