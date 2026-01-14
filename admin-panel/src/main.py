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
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Literal
from contextlib import asynccontextmanager
from functools import wraps

import docker
import redis
import itsdangerous
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, Query, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, validator, EmailStr
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, func, Text, text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship

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
REDIS_DB = 1 # Use DB 1 for sessions to separate from queues/cache
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)

# Security Configuration
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
if not ADMIN_PASSWORD or ADMIN_PASSWORD == "admin":
    logger.warning("⚠️ ADMIN_PASSWORD not set or using default! Set a strong password in production.")
    ADMIN_PASSWORD = ADMIN_PASSWORD or "admin"

# Secret key for signing tokens (generate if not provided)
SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", secrets.token_hex(32))
SESSION_TTL_HOURS = 24 * 7 # 7 days session persistence
TOKEN_EXPIRY_HOURS = SESSION_TTL_HOURS # Align token expiry with session TTL

# Session Signer
signer = itsdangerous.TimestampSigner(SECRET_KEY)

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


class MonitoringGroup(Base):
    __tablename__ = "monitoring_groups"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), index=True)
    interval_seconds = Column(Integer, default=60)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    targets = relationship("MonitoredTarget", back_populates="group", cascade="all, delete-orphan")


class MonitoredTarget(Base):
    __tablename__ = "monitored_targets"
    __table_args__ = {'extend_existing': True}
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("monitoring_groups.id"), nullable=True)
    name = Column(String(100), index=True)
    hostname = Column(String(255))
    interval_seconds = Column(Integer, default=60)
    is_active = Column(Boolean, default=True)
    last_status = Column(String(20), nullable=True)
    last_check = Column(DateTime(timezone=True), nullable=True)

    group = relationship("MonitoringGroup", back_populates="targets")


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


class WorkstationRange(Base):
    __tablename__ = "workstation_ranges"
    id = Column(Integer, primary_key=True, index=True)
    prefix = Column(String(20), nullable=False)
    range_start = Column(Integer, nullable=False)
    range_end = Column(Integer, nullable=False)
    description = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)


# Note: In production, use Alembic migrations instead of create_all()
Base.metadata.create_all(bind=engine)


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

def initials_filter(value):
    """Jinja2 filter to extract initials from name."""
    if not value: return "?"
    parts = value.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return value[:2].upper()

templates.env.filters["initials"] = initials_filter

app = FastAPI(title="NetAdmin Control Plane", version="3.0.0")

# Mount static files
app.mount("/static", StaticFiles(directory="src/static"), name="static")


# --- Global Exception Handlers (Auth & HTMX) ---

class AuthenticationError(Exception):
    """Custom exception for authentication failures."""
    pass

@app.exception_handler(AuthenticationError)
async def auth_exception_handler(request: Request, exc: AuthenticationError):
    """
    Handle auth errors globally.
    - HTMX requests: Send HX-Redirect header (client-side redirect).
    - Browser requests: Send 302 Found (server-side redirect).
    """
    if request.headers.get("HX-Request"):
        logger.info(f"HTMX Auth Error: Redirecting to /login (Path: {request.url.path})")
        return Response(
            content="Session expired", 
            status_code=401,
            headers={"HX-Redirect": "/login"}
        )
    
    logger.info(f"Browser Auth Error: Redirecting to /login (Path: {request.url.path})")
    return RedirectResponse(
        url="/login", 
        status_code=status.HTTP_302_FOUND
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """
    Catch all HTTPException and handle 401s specially for HTMX.
    This ensures expired sessions always redirect cleanly, no broken partials.
    """
    if exc.status_code == 401:
        if request.headers.get("HX-Request"):
            logger.info(f"HTMX 401 Unauthorized: Redirecting to /login (Path: {request.url.path})")
            return Response(
                content="Unauthorized - Please login again",
                status_code=401,
                headers={"HX-Redirect": "/login"}
            )
        
        logger.info(f"Browser 401 Unauthorized: Redirecting to /login (Path: {request.url.path})")
        return RedirectResponse(
            url="/login",
            status_code=status.HTTP_302_FOUND
        )
    
    # For non-401 errors, return default JSON error
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )


# --- Authentication Helpers (Redis Sessions) ---

def create_session(user_id: str, role: str = "admin") -> str:
    """Create a new session in Redis and return the signed session ID."""
    session_id = str(uuid.uuid4())
    session_data = {
        "user_id": user_id,
        "role": role,
        "created_at": datetime.utcnow().isoformat()
    }
    # Store in Redis with TTL
    redis_key = f"session:{session_id}"
    redis_client.hset(redis_key, mapping=session_data)
    redis_client.expire(redis_key, timedelta(hours=SESSION_TTL_HOURS))
    
    # Sign the session ID to prevent tampering
    signed_session_id = signer.sign(session_id).decode('utf-8')
    return signed_session_id

def get_current_session(request: Request) -> Optional[dict]:
    """Retrieve and validate the session from the cookie."""
    signed_session_id = request.cookies.get("session_id")
    if not signed_session_id:
        return None
    
    try:
        # Verify signature and get original session ID
        # max_age ensures the signature itself hasn't expired (double check)
        session_id = signer.unsign(signed_session_id, max_age=SESSION_TTL_HOURS * 3600).decode('utf-8')
    except (itsdangerous.BadSignature, itsdangerous.SignatureExpired):
        return None
        
    # Check Redis
    redis_key = f"session:{session_id}"
    session_data = redis_client.hgetall(redis_key)
    
    if not session_data:
        return None
        
    # Refresh TTL on activity (sliding expiration)
    redis_client.expire(redis_key, timedelta(hours=SESSION_TTL_HOURS))
    
    return session_data

def verify_auth(request: Request):
    """Dependency to enforce authentication."""
    session = get_current_session(request)
    if not session:
        raise AuthenticationError()
    return True

def verify_auth_soft(request: Request) -> bool:
    """Check auth without raising exception (for conditional rendering)."""
    return get_current_session(request) is not None


# --- Routes ---

@app.on_event("startup")
async def startup_event():
    """Run on startup: Create tables and ensure schema is up to date."""
    try:
        Base.metadata.create_all(bind=engine)
        
        # Emergency Schema Sync: Add group_id if it's missing (for existing installations)
        with engine.connect() as conn:
            try:
                conn.execute(text("ALTER TABLE monitored_targets ADD COLUMN IF NOT EXISTS group_id INTEGER REFERENCES monitoring_groups(id)"))
                conn.commit()
            except Exception as schema_err:
                logger.warning(f"Schema sync warning (group_id): {schema_err}")
                
        logger.info("Database tables verified/created.")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """Main dashboard page."""
    if not verify_auth_soft(request):
        return templates.TemplateResponse("login.html", {"request": request})
    
    # 1. Get Monitoring Stats (with safety fallback)
    targets = []
    try:
        targets = db.query(MonitoredTarget).all()
    except Exception as e:
        logger.error(f"Dashboard Monitoring Query Failed: {e}")
    
    # 2. Get Containers
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

    # 3. Get Backups
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
        "backups": backups,
        "current_page": "dashboard"
    })


@app.get("/monitoring", response_class=HTMLResponse)
async def monitoring_page(request: Request, db: Session = Depends(get_db), _: bool = Depends(verify_auth)):
    """Monitoring groups & targets page."""
    groups = []
    ungrouped_targets = []
    try:
        groups = db.query(MonitoringGroup).order_by(MonitoringGroup.name).all()
        ungrouped_targets = db.query(MonitoredTarget).filter(MonitoredTarget.group_id == None).all()
    except Exception as e:
        logger.error(f"Monitoring Page Query Failed: {e}")
    
    return templates.TemplateResponse("monitoring.html", {
        "request": request,
        "groups": groups,
        "ungrouped_targets": ungrouped_targets,
        "current_page": "monitoring"
    })

@app.post("/api/monitoring/groups")
async def create_monitoring_group(
    name: str = Form(...),
    interval: int = Form(...),
    db: Session = Depends(get_db),
    _: bool = Depends(verify_auth)
):
    """Create a new monitoring group."""
    new_group = MonitoringGroup(name=name, interval_seconds=interval)
    db.add(new_group)
    db.commit()
    return RedirectResponse(url="/monitoring", status_code=status.HTTP_303_SEE_OTHER)

@app.delete("/api/monitoring/groups/{group_id}")
async def delete_monitoring_group(group_id: int, db: Session = Depends(get_db), _: bool = Depends(verify_auth)):
    """Delete a monitoring group and all its targets."""
    try:
        # Delete all targets in this group first
        db.query(MonitoredTarget).filter(MonitoredTarget.group_id == group_id).delete()
        # Then delete the group
        deleted = db.query(MonitoringGroup).filter(MonitoringGroup.id == group_id).delete()
        if not deleted:
            raise HTTPException(status_code=404, detail="Group not found")
        db.commit()
        try:
            redis_client.publish("netadmin_events", "CONFIG_UPDATE:MONITORING")
        except:
            pass
        logger.info(f"Deleted monitoring group: {group_id}")
        # Return empty 200 response for HTMX to handle cleanly
        return Response(status_code=200)
    except Exception as e:
        logger.error(f"Error deleting monitoring group {group_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/monitoring/targets")
async def create_monitoring_target(
    name: str = Form(...),
    hostname: str = Form(...),
    group_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    _: bool = Depends(verify_auth)
):
    """Create a new monitoring target within a group."""
    interval = 60
    if group_id:
        group = db.query(MonitoringGroup).filter(MonitoringGroup.id == group_id).first()
        if group: interval = group.interval_seconds

    new_target = MonitoredTarget(name=name, hostname=hostname, group_id=group_id, interval_seconds=interval)
    db.add(new_target)
    db.commit()
    try: redis_client.publish("netadmin_events", "CONFIG_UPDATE:MONITORING")
    except: pass
    return RedirectResponse(url="/monitoring", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Render login page (GET)."""
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/backups", response_class=HTMLResponse)
async def backups_page(request: Request, _: bool = Depends(verify_auth)):
    """System backups page."""
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
    
    return templates.TemplateResponse("backups.html", {
        "request": request,
        "backups": backups,
        "current_page": "backups"
    })


@app.post("/login", response_class=RedirectResponse)
async def login(request: Request, password: str = Form(...)):
    """Handle login and set session cookie."""
    if verify_password(password, ADMIN_PASSWORD):
        # Create persistent session
        session_id = create_session("admin_user")
        
        response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        response.set_cookie(
            key="session_id",
            value=session_id,
            httponly=True,
            samesite="lax",
            max_age=SESSION_TTL_HOURS * 3600
        )
        return response
    
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": "Invalid password"
    })


@app.post("/logout")
async def logout(request: Request):
    """Clear session and redirect to login."""
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    # Optional: Delete from Redis explicitly
    signed_session_id = request.cookies.get("session_id")
    if signed_session_id:
        try:
            session_id = signer.unsign(signed_session_id).decode('utf-8')
            redis_client.delete(f"session:{session_id}")
        except:
            pass
            
    response.delete_cookie("session_id")
    return response


@app.get("/api/config/ranges")
@app.get("/api/config/ranges", response_class=HTMLResponse)
async def get_workstation_config(request: Request, db: Session = Depends(get_db), _: bool = Depends(verify_auth)):
    """Return HTML partial for workstation ranges configuration."""
    ranges = db.query(WorkstationRange).filter(WorkstationRange.is_active == True).all()
    return templates.TemplateResponse("partials/ws_config.html", {
        "request": request,
        "ranges": ranges
    })

@app.get("/api/workstation-ranges")
async def get_workstation_ranges(db: Session = Depends(get_db), _: bool = Depends(verify_auth)):
    """Get all configured workstation ranges (JSON)."""
    ranges = db.query(WorkstationRange).filter(WorkstationRange.is_active == True).all()
    return [{
        "id": r.id,
        "prefix": r.prefix,
        "range_start": r.range_start,
        "range_end": r.range_end,
        "description": r.description
    } for r in ranges]

@app.get("/api/free-workstations", response_class=HTMLResponse)
async def get_free_workstations(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_auth)
):
    """
    Calculate free workstations SERVER-SIDE and return HTML partial.
    
    **Why Server-Side?**
    - Prevents UI freeze on large datasets
    - Shows loading spinner during calculation
    - Clean separation of concerns
    
    **Usage:** Called via HTMX lazy load: hx-get="/api/free-workstations" hx-trigger="load"
    """
    # 1. Get all active ranges
    ranges = db.query(WorkstationRange).filter(WorkstationRange.is_active == True).all()
    
    # 2. Get all occupied workstations
    occupied_ws = set()
    employees = db.query(Employee).filter(Employee.workstation.isnot(None)).all()
    for emp in employees:
        if emp.workstation:
            occupied_ws.add(emp.workstation.strip().upper())
    
    # 3. Calculate free workstations per prefix
    groups = []
    for r in ranges:
        prefix = r.prefix.upper()
        # FIX: Ensure 3-digit padding (WS001)
        all_ws_in_range = [f"{prefix}{i:03d}" for i in range(r.range_start, r.range_end + 1)]
        free_ws = [ws for ws in all_ws_in_range if ws not in occupied_ws]
        
        groups.append({
            "prefix": prefix,
            "ids": free_ws,
            "total": len(all_ws_in_range),
            "range": f"{r.range_start}-{r.range_end}"
        })
    
    # 4. Return HTML partial (for HTMX swap)
    return templates.TemplateResponse("partials/free_ws.html", {
        "request": request,
        "groups": groups
    })

@app.post("/api/workstation-ranges")
async def create_workstation_range(
    prefix: str = Form(...),
    start: int = Form(...),
    end: int = Form(...),
    description: str = Form(None),
    db: Session = Depends(get_db),
    _: bool = Depends(verify_auth)
):
    """Create a new workstation range."""
    new_range = WorkstationRange(
        prefix=prefix.upper(),
        range_start=start,
        range_end=end,
        description=description
    )
    db.add(new_range)
    db.commit()
    return {"status": "success"}

@app.delete("/api/workstation-ranges/{range_id}")
async def delete_workstation_range(range_id: int, db: Session = Depends(get_db), _: bool = Depends(verify_auth)):
    """Delete (deactivate) a workstation range."""
    r = db.query(WorkstationRange).filter(WorkstationRange.id == range_id).first()
    if r:
        r.is_active = False
        db.commit()
    return {"status": "success"}


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


@app.delete("/api/targets/{target_id}")
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
    return Response(status_code=status.HTTP_200_OK)


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


@app.get("/inventory/rows", response_class=HTMLResponse)
@app.get("/inventory", response_class=HTMLResponse)
async def inventory_page(
    request: Request,
    search: Optional[str] = Query(None, max_length=100),
    sort: Optional[str] = Query(None, max_length=50),  # None = use default
    order: Literal["asc", "desc"] = "asc",
    department: Optional[str] = Query(None, max_length=100),  # None/empty = ALL
    company: Optional[str] = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    _: bool = Depends(verify_auth)
):
    """
    Inventory Grid UI V3.1 - Server-Side Rendering & HTMX.
    
    **Defaults:**
    - Department: ALL (no filter)
    - Sort: ID ASC (stable, predictable)
    - Pagination: 50 items per page
    
    **Performance:**
    - Server-side filtering/sorting/pagination
    - Returns full page or HTMX partial (table rows only)
    """
    query = db.query(Employee)
    
    # 1. Filtering
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
    
    # Department Filter: Only apply if explicitly provided and not empty
    if department and department.strip():
        if department == 'Factory':
             query = query.filter(Employee.department.ilike("%Factory%"))
        else:
             query = query.filter(Employee.department == department)
             
    # Company Filter: Only apply if explicitly provided and not 'all'
    if company and company != 'all':
        query = query.filter(Employee.company == company)

    # 2. Sorting - Default to ID ASC for stability
    validated_sort = SortColumn.validate(sort) if sort else None
    if validated_sort:
        sort_column = getattr(Employee, validated_sort, None)
        if sort_column is not None:
            if order == "desc":
                query = query.order_by(sort_column.desc())
            else:
                query = query.order_by(sort_column.asc())
        else:
            # Fallback to ID if column lookup fails
            query = query.order_by(Employee.id.asc())
    else:
        # Default: Sort by ID ASC (Stable, Predictable)
        query = query.order_by(Employee.id.asc())

    # 3. Pagination
    total_count = query.count()
    total_pages = (total_count + limit - 1) // limit
    
    employees_rows = query.offset((page - 1) * limit).limit(limit).all()
    
    employees = []
    for e in employees_rows:
        employees.append({
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
            "has_ad": e.has_ad,
            "has_drweb": e.has_drweb,
            "has_zabbix": e.has_zabbix,
            "ad_login": e.ad_login,
            "notes": e.notes,
            "is_active": e.is_active
        })
    
    # 4. HTMX Partial Response (Table Rows Only)
    if "/rows" in str(request.url.path) or (request.headers.get("HX-Request") and request.headers.get("HX-Target") == "inventory-table-body"):
        return templates.TemplateResponse("partials/inventory_rows.html", {
            "request": request, 
            "employees": employees
        })

    # 5. Full Page Response
    return templates.TemplateResponse("inventory.html", {
        "request": request,
        "employees": employees,
        "search": search or "",
        "sort": sort or "id",  # Default display: "id"
        "order": order,
        "department": department or "",  # Empty = ALL
        "company": company or "all",
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "total_count": total_count,
        "current_page": "inventory"
    })


@app.get("/api/employees/{employee_id}/form", response_class=HTMLResponse)
async def get_employee_form(
    employee_id: str, # 'new' or integer ID
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_auth)
):
    """Return a server-rendered form for Add/Edit Employee."""
    if employee_id == "new":
        employee = None
    else:
        employee = db.query(Employee).filter(Employee.id == int(employee_id)).first()
        if not employee:
            raise HTTPException(status_code=404, detail="Employee not found")

    return templates.TemplateResponse("partials/employee_form.html", {
        "request": request,
        "employee": employee
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
    """Update employee - accepts Form data from HTMX."""
    logger.info(f"PATCH /api/employees/{employee_id} - Data: {full_name}, {company}, {department}")
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    try:
        # Update fields
        last_name, first_name, middle_name = parse_fio(full_name)
        employee.last_name = last_name
        employee.first_name = first_name
        employee.middle_name = middle_name
        employee.company = company
        employee.department = department
        employee.location = location
        employee.internal_phone = internal_phone
        employee.phone_type = phone_type or 'NONE'
        employee.workstation = workstation
        employee.device_type = device_type
        employee.specs_cpu = specs_cpu
        employee.specs_gpu = specs_gpu
        employee.specs_ram = specs_ram
        employee.monitor = monitor
        employee.ups = ups
        employee.has_ad = has_ad
        employee.has_drweb = has_drweb
        employee.has_zabbix = has_zabbix
        employee.ad_login = ad_login
        employee.email = email
        employee.notes = notes
        
        db.commit()
        logger.info(f"Updated employee: {full_name} (ID: {employee_id})")
        
        # Return fresh list partial
        employees = db.query(Employee).order_by(Employee.id.asc()).limit(50).all()
        return templates.TemplateResponse("partials/inventory_rows.html", {
            "request": request,
            "employees": employees
        })
    except Exception as e:
        logger.error(f"Error updating employee {employee_id}: {e}")
        raise HTTPException(status_code=400, detail=str(e))


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

@app.get("/api/docker/logs/{container_id}")
async def get_docker_logs(container_id: str, _: bool = Depends(verify_auth)):
    """Fetch Docker container logs (last 50 lines)."""
    try:
        container = docker_client.containers.get(container_id)
        logs = container.logs(tail=50, stdout=True, stderr=True).decode('utf-8', errors='replace')
        return Response(content=logs, media_type="text/plain")
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail="Container not found")
    except Exception as e:
        logger.error(f"Docker logs error: {e}")
        return Response(content=f"Error fetching logs: {e}", media_type="text/plain")

@app.get("/health")
async def health_check():
    """Health check endpoint for Docker/Kubernetes."""
    return {"status": "healthy", "version": "3.0.0"}
