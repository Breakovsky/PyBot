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

class Employee(Base):
    __tablename__ = "employees"
    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False, index=True)
    department = Column(String)
    phone = Column(String, index=True)
    workstation = Column(String, index=True)
    ad_login = Column(String, index=True)
    email = Column(String, index=True)
    notes = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

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

# --- Inventory Management (Phase 5) ---
@app.get("/inventory", response_class=HTMLResponse)
async def inventory_page(
    request: Request,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    _: None = Depends(verify_auth)
):
    """Inventory Grid UI - Google Sheets-like experience."""
    query = db.query(Employee)
    
    # Search filter
    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            (Employee.full_name.ilike(search_filter)) |
            (Employee.phone.ilike(search_filter)) |
            (Employee.workstation.ilike(search_filter)) |
            (Employee.ad_login.ilike(search_filter)) |
            (Employee.email.ilike(search_filter))
        )
    
    employees = query.order_by(Employee.full_name).limit(500).all()
    
    return templates.TemplateResponse("inventory.html", {
        "request": request,
        "employees": employees,
        "search": search or ""
    })

@app.get("/api/employees")
async def get_employees(
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    _: None = Depends(verify_auth)
):
    """Get employees as JSON (for AJAX updates)."""
    query = db.query(Employee)
    
    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            (Employee.full_name.ilike(search_filter)) |
            (Employee.phone.ilike(search_filter)) |
            (Employee.workstation.ilike(search_filter))
        )
    
    total = query.count()
    employees = query.order_by(Employee.full_name).offset(offset).limit(limit).all()
    
    return {
        "total": total,
        "employees": [
            {
                "id": e.id,
                "full_name": e.full_name,
                "department": e.department,
                "phone": e.phone,
                "workstation": e.workstation,
                "ad_login": e.ad_login,
                "email": e.email,
                "notes": e.notes,
                "is_active": e.is_active
            }
            for e in employees
        ]
    }

@app.post("/api/employees")
async def create_employee(
    full_name: str = Form(...),
    department: str = Form(None),
    phone: str = Form(None),
    workstation: str = Form(None),
    ad_login: str = Form(None),
    email: str = Form(None),
    notes: str = Form(None),
    db: Session = Depends(get_db),
    _: None = Depends(verify_auth)
):
    """Create new employee."""
    employee = Employee(
        full_name=full_name,
        department=department,
        phone=phone,
        workstation=workstation,
        ad_login=ad_login,
        email=email,
        notes=notes
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)
    
    return {"status": "success", "id": employee.id}

@app.patch("/api/employees/{employee_id}")
async def update_employee(
    employee_id: int,
    full_name: Optional[str] = None,
    department: Optional[str] = None,
    phone: Optional[str] = None,
    workstation: Optional[str] = None,
    ad_login: Optional[str] = None,
    email: Optional[str] = None,
    notes: Optional[str] = None,
    db: Session = Depends(get_db),
    _: None = Depends(verify_auth)
):
    """Update employee (inline edit)."""
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    # Update only provided fields
    if full_name is not None:
        employee.full_name = full_name
    if department is not None:
        employee.department = department
    if phone is not None:
        employee.phone = phone
    if workstation is not None:
        employee.workstation = workstation
    if ad_login is not None:
        employee.ad_login = ad_login
    if email is not None:
        employee.email = email
    if notes is not None:
        employee.notes = notes
    
    employee.updated_at = func.now()
    db.commit()
    
    return {"status": "success"}

@app.post("/api/employees/{employee_id}/toggle")
async def toggle_employee(
    employee_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(verify_auth)
):
    """Toggle employee active status (disable/enable)."""
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    employee.is_active = not employee.is_active
    employee.updated_at = func.now()
    db.commit()
    
    return {"status": "success", "is_active": employee.is_active}

@app.delete("/api/employees/{employee_id}")
async def delete_employee(
    employee_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(verify_auth)
):
    """Delete employee (hard delete)."""
    db.query(Employee).filter(Employee.id == employee_id).delete()
    db.commit()
    
    return {"status": "success"}
