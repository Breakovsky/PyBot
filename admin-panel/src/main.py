"""
NetAdmin Control Plane - Admin Panel
=====================================
FastAPI-based admin interface for infrastructure management.

Security Features:
- JWT-like token authentication (signed cookies)
- CSRF protection via SameSite cookies
- Input validation via Pydantic models
- SQL injection prevention via parameterized queries
- XSS prevention via Jinja2 auto-escaping
"""

import os
import logging
import secrets
import hashlib
import hmac
from datetime import datetime, timedelta
from typing import List, Optional, Literal
from contextlib import asynccontextmanager
from functools import wraps

import docker
import redis
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, validator, EmailStr
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, func, Text, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# --- Configuration ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database Configuration
POSTGRES_USER = os.getenv("POSTGRES_USER", "netadmin")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "netadmin_secret")
POSTGRES_DB = os.getenv("POSTGRES_DB", "netadmin_db")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "db")
DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}/{POSTGRES_DB}"

# Redis Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# Security Configuration
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
if not ADMIN_PASSWORD or ADMIN_PASSWORD == "admin":
    logger.warning("⚠️ ADMIN_PASSWORD not set or using default! Set a strong password in production.")
    ADMIN_PASSWORD = ADMIN_PASSWORD or "admin"

# Secret key for signing tokens (generate if not provided)
SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", secrets.token_hex(32))
TOKEN_EXPIRY_HOURS = 24

# --- Pydantic Models (Request/Response Validation) ---

class EmployeeCreate(BaseModel):
    """Validated employee creation request."""
    full_name: str = Field(..., min_length=2, max_length=255)
    company: Optional[str] = Field(None, max_length=100)
    department: Optional[str] = Field(None, max_length=255)
    location: Optional[str] = Field(None, max_length=255)
    internal_phone: Optional[str] = Field(None, max_length=50)
    phone_type: Literal['TA', 'MicroSIP', 'NONE'] = 'NONE'
    workstation: Optional[str] = Field(None, max_length=100)
    device_type: Optional[Literal['PC', 'Laptop', 'Monoblock', 'Server', 'Other']] = None
    specs_cpu: Optional[str] = Field(None, max_length=255)
    specs_gpu: Optional[str] = Field(None, max_length=255)
    specs_ram: Optional[str] = Field(None, max_length=50)
    monitor: Optional[str] = Field(None, max_length=255)
    ups: Optional[str] = Field(None, max_length=255)
    ad_login: Optional[str] = Field(None, max_length=100)
    email: Optional[str] = Field(None, max_length=255)
    has_ad: bool = False
    has_drweb: bool = False
    has_zabbix: bool = False
    notes: Optional[str] = None

    @validator('email')
    def validate_email(cls, v):
        if v and '@' not in v:
            raise ValueError('Invalid email format')
        return v


class EmployeeUpdate(BaseModel):
    """Validated employee update request (partial)."""
    full_name: Optional[str] = Field(None, min_length=2, max_length=255)
    department: Optional[str] = Field(None, max_length=255)
    internal_phone: Optional[str] = Field(None, max_length=50)
    workstation: Optional[str] = Field(None, max_length=100)
    ad_login: Optional[str] = Field(None, max_length=100)
    email: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None


class TargetCreate(BaseModel):
    """Validated monitoring target creation."""
    name: str = Field(..., min_length=1, max_length=100)
    hostname: str = Field(..., min_length=1, max_length=255)
    interval: int = Field(..., ge=10, le=3600)  # 10s to 1h


class SortColumn:
    """Whitelist for sortable columns - prevents SQL injection via getattr."""
    ALLOWED_COLUMNS = frozenset({
        'id', 'last_name', 'first_name', 'company', 'department', 
        'location', 'workstation', 'internal_phone', 'email', 'ad_login'
    })
    
    @classmethod
    def validate(cls, column: Optional[str]) -> Optional[str]:
        """Validate column name against whitelist."""
        if column and column in cls.ALLOWED_COLUMNS:
            return column
        return None


# --- Database Setup ---
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class MonitoredTarget(Base):
    __tablename__ = "monitored_targets"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), index=True)
    hostname = Column(String(255))
    interval_seconds = Column(Integer, default=60)
    is_active = Column(Boolean, default=True)
    last_status = Column(String(20), nullable=True)
    last_check = Column(DateTime(timezone=True), nullable=True)


class Employee(Base):
    __tablename__ = "employees"
    id = Column(Integer, primary_key=True, index=True)
    
    # Identity & Organization
    company = Column(String(100), index=True)
    last_name = Column(String(100), index=True)
    first_name = Column(String(100), index=True)
    middle_name = Column(String(100), index=True)
    department = Column(String(255), index=True)
    location = Column(String(255), index=True)
    
    # Contact Information
    email = Column(String(255), index=True)
    phone_type = Column(String(20))
    internal_phone = Column(String(50), index=True)
    
    # Hardware Inventory
    workstation = Column(String(100), index=True)
    device_type = Column(String(50))
    specs_cpu = Column(String(255))
    specs_gpu = Column(String(255))
    specs_ram = Column(String(50))
    monitor = Column(String(255))
    ups = Column(String(255))
    
    # Software Status
    has_ad = Column(Boolean, default=False)
    has_drweb = Column(Boolean, default=False)
    has_zabbix = Column(Boolean, default=False)
    
    # Additional
    ad_login = Column(String(100), index=True)
    notes = Column(Text)
    is_active = Column(Boolean, default=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    @property
    def full_name(self) -> Optional[str]:
        """Construct full name from parts."""
        parts = [self.last_name or "", self.first_name or "", self.middle_name or ""]
        return " ".join(p for p in parts if p).strip() or None


# Note: In production, use Alembic migrations instead of create_all()
# Base.metadata.create_all(bind=engine)


def get_db():
    """Database session dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- Security Utilities ---

def generate_token(user_id: str = "admin") -> str:
    """Generate a signed authentication token."""
    timestamp = int(datetime.utcnow().timestamp())
    payload = f"{user_id}:{timestamp}"
    signature = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"


def verify_token(token: str) -> bool:
    """Verify authentication token signature and expiry."""
    if not token:
        return False
    
    try:
        parts = token.split(":")
        if len(parts) != 3:
            return False
        
        user_id, timestamp_str, signature = parts
        timestamp = int(timestamp_str)
        
        # Check expiry
        token_time = datetime.utcfromtimestamp(timestamp)
        if datetime.utcnow() - token_time > timedelta(hours=TOKEN_EXPIRY_HOURS):
            logger.warning("Token expired")
            return False
        
        # Verify signature
        payload = f"{user_id}:{timestamp_str}"
        expected_signature = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
        
        if not hmac.compare_digest(signature, expected_signature):
            logger.warning("Invalid token signature")
            return False
        
        return True
    
    except Exception as e:
        logger.error(f"Token verification error: {e}")
        return False


def verify_password(provided: str, expected: str) -> bool:
    """Constant-time password comparison."""
    return hmac.compare_digest(provided.encode(), expected.encode())


# --- Docker & Redis Clients ---
docker_client = docker.from_env()
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


# --- FastAPI App ---
templates = Jinja2Templates(directory="src/templates")
app = FastAPI(title="NetAdmin Control Plane", version="3.0.0")


# --- Auth Dependencies ---

def get_auth_token(request: Request) -> Optional[str]:
    """Extract auth token from cookie."""
    return request.cookies.get("admin_token")


def verify_auth(request: Request) -> bool:
    """Verify authentication - raises HTTPException if invalid."""
    token = get_auth_token(request)
    if not verify_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    return True


def verify_auth_soft(request: Request) -> bool:
    """Verify authentication - returns False instead of raising."""
    token = get_auth_token(request)
    return verify_token(token)


# --- Routes ---

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """Main dashboard page."""
    if not verify_auth_soft(request):
        return templates.TemplateResponse("login.html", {"request": request})
    
    targets = db.query(MonitoredTarget).all()
    
    # Get Containers
    containers = []
    try:
        for c in docker_client.containers.list(all=True):
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
    """Handle login form submission."""
    if verify_password(password, ADMIN_PASSWORD):
        response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        token = generate_token()
        response.set_cookie(
            key="admin_token",
            value=token,
            httponly=True,
            secure=os.getenv("HTTPS_ENABLED", "false").lower() == "true",
            samesite="lax",
            max_age=TOKEN_EXPIRY_HOURS * 3600
        )
        logger.info("Admin login successful")
        return response
    
    logger.warning("Failed login attempt")
    return RedirectResponse(url="/?error=Invalid+Password", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/logout")
async def logout():
    """Handle logout."""
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("admin_token")
    return response


# --- Container Operations ---

@app.post("/api/containers/{container_id}/restart")
async def restart_container(container_id: str, _: bool = Depends(verify_auth)):
    """Restart a Docker container."""
    try:
        container = docker_client.containers.get(container_id)
        container.restart()
        logger.info(f"Container {container.name} restarted")
        return {"status": "success", "message": f"Container {container.name} restarting..."}
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail="Container not found")
    except Exception as e:
        logger.error(f"Container restart error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/containers/{container_id}/logs")
async def get_logs(container_id: str, _: bool = Depends(verify_auth)):
    """Get container logs."""
    try:
        container = docker_client.containers.get(container_id)
        logs = container.logs(tail=100).decode('utf-8', errors='replace')
        return {"logs": logs}
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail="Container not found")
    except Exception as e:
        logger.error(f"Get logs error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Target Operations ---

@app.post("/api/targets")
async def create_target(
    name: str = Form(...),
    hostname: str = Form(...),
    interval: int = Form(...),
    db: Session = Depends(get_db),
    _: bool = Depends(verify_auth)
):
    """Create a new monitoring target."""
    # Validate via Pydantic
    try:
        validated = TargetCreate(name=name, hostname=hostname, interval=interval)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    target = MonitoredTarget(
        name=validated.name,
        hostname=validated.hostname,
        interval_seconds=validated.interval
    )
    db.add(target)
    db.commit()
    
    # Notify Java Agent
    try:
        redis_client.publish("netadmin_events", "CONFIG_UPDATE:MONITORING")
    except Exception as e:
        logger.error(f"Redis publish error: {e}")
    
    logger.info(f"Created monitoring target: {validated.name}")
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/api/targets/{target_id}/delete")
async def delete_target(
    target_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_auth)
):
    """Delete a monitoring target."""
    deleted = db.query(MonitoredTarget).filter(MonitoredTarget.id == target_id).delete()
    if not deleted:
        raise HTTPException(status_code=404, detail="Target not found")
    
    db.commit()
    
    # Notify Java Agent
    try:
        redis_client.publish("netadmin_events", "CONFIG_UPDATE:MONITORING")
    except Exception as e:
        logger.error(f"Redis publish error: {e}")
    
    logger.info(f"Deleted monitoring target: {target_id}")
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


# --- Backup Operations ---

@app.get("/api/backups/download/{filename}")
async def download_backup(filename: str, _: bool = Depends(verify_auth)):
    """Download a backup file."""
    # Sanitize filename (prevent path traversal)
    safe_filename = os.path.basename(filename)
    if safe_filename != filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    file_path = os.path.join("/backups", safe_filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(file_path, filename=safe_filename)


# --- Inventory Management ---

def parse_fio(full_name: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Parse Russian FIO format: 'Фамилия Имя Отчество' into parts."""
    if not full_name:
        return (None, None, None)
    parts = full_name.strip().split()
    if len(parts) == 0:
        return (None, None, None)
    elif len(parts) == 1:
        return (parts[0], None, None)
    elif len(parts) == 2:
        return (parts[0], parts[1], None)
    else:
        return (parts[0], parts[1], " ".join(parts[2:]))


@app.get("/inventory", response_class=HTMLResponse)
async def inventory_page(
    request: Request,
    search: Optional[str] = Query(None, max_length=100),
    sort: Optional[str] = Query(None, max_length=50),
    order: Literal["asc", "desc"] = "asc",
    db: Session = Depends(get_db),
    _: bool = Depends(verify_auth)
):
    """Inventory Grid UI V2.0 - with sorting and expandable rows."""
    query = db.query(Employee)
    
    # Search filter - search in all name parts and other fields
    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            (Employee.last_name.ilike(search_filter)) |
            (Employee.first_name.ilike(search_filter)) |
            (Employee.middle_name.ilike(search_filter)) |
            (Employee.company.ilike(search_filter)) |
            (Employee.department.ilike(search_filter)) |
            (Employee.location.ilike(search_filter)) |
            (Employee.internal_phone.ilike(search_filter)) |
            (Employee.workstation.ilike(search_filter)) |
            (Employee.ad_login.ilike(search_filter)) |
            (Employee.email.ilike(search_filter))
        )
    
    # Validate and apply sorting (whitelist approach)
    validated_sort = SortColumn.validate(sort)
    if validated_sort:
        sort_column = getattr(Employee, validated_sort, None)
        if sort_column is not None:
            if order == "desc":
                query = query.order_by(sort_column.desc())
            else:
                query = query.order_by(sort_column.asc())
    else:
        # Default sort by last_name, first_name
        query = query.order_by(Employee.last_name, Employee.first_name)
    
    employees = query.limit(2000).all()
    
    # Convert to JSON-serializable format for Alpine.js
    employees_data = []
    for e in employees:
        employees_data.append({
            "id": e.id,
            "full_name": e.full_name,
            "company": e.company,
            "department": e.department,
            "location": e.location,
            "email": e.email,
            "phone_type": e.phone_type,
            "internal_phone": e.internal_phone,
            "workstation": e.workstation,
            "device_type": e.device_type,
            "specs_cpu": e.specs_cpu,
            "specs_gpu": e.specs_gpu,
            "specs_ram": e.specs_ram,
            "monitor": e.monitor,
            "ups": e.ups,
            "has_ad": e.has_ad or False,
            "has_drweb": e.has_drweb or False,
            "has_zabbix": e.has_zabbix or False,
            "ad_login": e.ad_login,
            "notes": e.notes,
            "is_active": e.is_active if e.is_active is not None else True
        })
    
    return templates.TemplateResponse("inventory.html", {
        "request": request,
        "employees": employees_data,
        "search": search or "",
        "sort": sort or "",
        "order": order
    })


@app.get("/api/employees")
async def get_employees(
    search: Optional[str] = Query(None, max_length=100),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: bool = Depends(verify_auth)
):
    """Get employees as JSON (for AJAX updates)."""
    query = db.query(Employee)
    
    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            (Employee.last_name.ilike(search_filter)) |
            (Employee.first_name.ilike(search_filter)) |
            (Employee.middle_name.ilike(search_filter)) |
            (Employee.company.ilike(search_filter)) |
            (Employee.department.ilike(search_filter)) |
            (Employee.location.ilike(search_filter)) |
            (Employee.internal_phone.ilike(search_filter)) |
            (Employee.workstation.ilike(search_filter))
        )
    
    total = query.count()
    employees = query.order_by(Employee.last_name, Employee.first_name).offset(offset).limit(limit).all()
    
    return {
        "total": total,
        "employees": [
            {
                "id": e.id,
                "full_name": e.full_name,
                "department": e.department,
                "internal_phone": e.internal_phone,
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
    company: str = Form(None),
    department: str = Form(None),
    location: str = Form(None),
    internal_phone: str = Form(None),
    phone_type: str = Form(None),
    workstation: str = Form(None),
    device_type: str = Form(None),
    specs_cpu: str = Form(None),
    specs_gpu: str = Form(None),
    specs_ram: str = Form(None),
    monitor: str = Form(None),
    ups: str = Form(None),
    ad_login: str = Form(None),
    email: str = Form(None),
    has_ad: bool = Form(False),
    has_drweb: bool = Form(False),
    has_zabbix: bool = Form(False),
    notes: str = Form(None),
    db: Session = Depends(get_db),
    _: bool = Depends(verify_auth)
):
    """Create new employee with all V2.0 fields."""
    # Validate via Pydantic
    try:
        validated = EmployeeCreate(
            full_name=full_name,
            company=company,
            department=department,
            location=location,
            internal_phone=internal_phone,
            phone_type=phone_type or 'NONE',
            workstation=workstation,
            device_type=device_type,
            specs_cpu=specs_cpu,
            specs_gpu=specs_gpu,
            specs_ram=specs_ram,
            monitor=monitor,
            ups=ups,
            ad_login=ad_login,
            email=email,
            has_ad=has_ad,
            has_drweb=has_drweb,
            has_zabbix=has_zabbix,
            notes=notes
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    last_name, first_name, middle_name = parse_fio(validated.full_name)
    employee = Employee(
        company=validated.company,
        last_name=last_name,
        first_name=first_name,
        middle_name=middle_name,
        department=validated.department,
        location=validated.location,
        internal_phone=validated.internal_phone,
        phone_type=validated.phone_type,
        workstation=validated.workstation,
        device_type=validated.device_type,
        specs_cpu=validated.specs_cpu,
        specs_gpu=validated.specs_gpu,
        specs_ram=validated.specs_ram,
        monitor=validated.monitor,
        ups=validated.ups,
        has_ad=validated.has_ad,
        has_drweb=validated.has_drweb,
        has_zabbix=validated.has_zabbix,
        ad_login=validated.ad_login,
        email=validated.email,
        notes=validated.notes
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)
    
    # Sync sequence after insert
    try:
        db.execute(text("SELECT sync_employees_id_sequence()"))
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to sync sequence: {e}")
    
    logger.info(f"Created employee: {employee.full_name} (ID: {employee.id})")
    return RedirectResponse(url="/inventory", status_code=status.HTTP_303_SEE_OTHER)


@app.patch("/api/employees/{employee_id}")
async def update_employee(
    employee_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_auth)
):
    """Update employee (inline edit) - accepts JSON body."""
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    try:
        body = await request.json()
        validated = EmployeeUpdate(**body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Update only provided fields
    if validated.full_name is not None:
        last_name, first_name, middle_name = parse_fio(validated.full_name)
        employee.last_name = last_name
        employee.first_name = first_name
        employee.middle_name = middle_name
    if validated.department is not None:
        employee.department = validated.department
    if validated.internal_phone is not None:
        employee.internal_phone = validated.internal_phone
    if validated.workstation is not None:
        employee.workstation = validated.workstation
    if validated.ad_login is not None:
        employee.ad_login = validated.ad_login
    if validated.email is not None:
        employee.email = validated.email
    if validated.notes is not None:
        employee.notes = validated.notes
    
    db.commit()
    logger.info(f"Updated employee: {employee.full_name} (ID: {employee_id})")
    
    return {"status": "success"}


@app.post("/api/employees/{employee_id}/toggle")
async def toggle_employee(
    employee_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_auth)
):
    """Toggle employee active status (disable/enable)."""
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    employee.is_active = not employee.is_active
    db.commit()
    
    logger.info(f"Toggled employee {employee_id}: is_active={employee.is_active}")
    return {"status": "success", "is_active": employee.is_active}


@app.delete("/api/employees/{employee_id}")
async def delete_employee(
    employee_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_auth)
):
    """Delete employee (hard delete)."""
    deleted = db.query(Employee).filter(Employee.id == employee_id).delete()
    if not deleted:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    db.commit()
    
    # Sync sequence after delete
    try:
        db.execute(text("SELECT sync_employees_id_sequence()"))
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to sync sequence: {e}")
    
    logger.info(f"Deleted employee: {employee_id}")
    
    return {"status": "success"}


# --- Health Check ---

@app.get("/health")
async def health_check():
    """Health check endpoint for Docker/Kubernetes."""
    return {"status": "healthy", "version": "3.0.0"}
