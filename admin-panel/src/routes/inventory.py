from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from typing import Optional, List

from ..main import templates, get_db, verify_auth, Employee

router = APIRouter()

# Allowed sort columns to prevent injection
SORT_COLUMNS = {
    "id": Employee.id,
    "full_name": (Employee.last_name, Employee.first_name),
    "department": Employee.department,
    "company": Employee.company,
}


def apply_sort(query, sort: str, order: str):
    column = SORT_COLUMNS.get(sort)
    if not column:
        return query.order_by(Employee.id.asc())
    if isinstance(column, tuple):
        cols: List = list(column)
    else:
        cols = [column]
    if order == "desc":
        cols = [c.desc() for c in cols]
    return query.order_by(*cols)


def paginate(query, page: int, limit: int):
    offset = (page - 1) * limit
    return query.offset(offset).limit(limit)


@router.get("/inventory", response_class=HTMLResponse)
async def inventory_page(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_auth),
    search: Optional[str] = Query(None),
    company: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    sort: str = Query("id"),
    order: str = Query("asc"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
):
    query = db.query(Employee)

    if company and company.lower() != "all":
        query = query.filter(Employee.company.ilike(company))
    if department and department.lower() != "all":
        query = query.filter(Employee.department.ilike(department))
    if search:
        term = f"%{search}%"
        query = query.filter(
            Employee.full_name.ilike(term)
            | Employee.department.ilike(term)
            | Employee.internal_phone.ilike(term)
            | Employee.workstation.ilike(term)
        )

    total = query.count()
    query = apply_sort(query, sort, order)
    employees = paginate(query, page, limit).all()

    context = {
        "request": request,
        "employees": employees,
        "search": search or "",
        "company": (company or "all").lower(),
        "department": (department or "all").lower(),
        "sort": sort,
        "order": order,
        "limit": limit,
        "page": page,
        "total": total,
    }

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("partials/inventory_rows.html", context)

    return templates.TemplateResponse("inventory.html", context)


@router.get("/inventory/rows", response_class=HTMLResponse)
async def inventory_rows(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_auth),
    search: Optional[str] = Query(None),
    company: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    sort: str = Query("id"),
    order: str = Query("asc"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
):
    # Delegate to inventory_page for consistent logic
    return await inventory_page(
        request=request,
        db=db,
        _=True,
        search=search,
        company=company,
        department=department,
        sort=sort,
        order=order,
        page=page,
        limit=limit,
    )

