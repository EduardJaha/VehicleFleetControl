from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_roles
from app.db.session import get_db
from app.models import User, Vehicle, VehicleBrand, VehicleModel
from app.schemas import (
    UserRole,
    VehicleBrandCreate,
    VehicleBrandOut,
    VehicleBrandUpdate,
    VehicleModelCreate,
    VehicleModelOut,
    VehicleModelUpdate,
)
from app.utils.vehicle_catalog import normalize_catalog_name

router = APIRouter(dependencies=[Depends(get_current_user)])


def brand_out(brand: VehicleBrand) -> VehicleBrandOut:
    return VehicleBrandOut(id=brand.id, name=brand.name, is_active=brand.is_active)


def model_out(model: VehicleModel) -> VehicleModelOut:
    return VehicleModelOut(
        id=model.id,
        brand_id=model.brand_id,
        name=model.name,
        is_active=model.is_active,
    )


def require_inactive_access(include_inactive: bool, user: User) -> None:
    if include_inactive and user.role != UserRole.admin.value:
        raise HTTPException(status_code=403, detail="Only Admin users can view inactive catalog entries.")


def commit_catalog_change(db: Session, duplicate_message: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=duplicate_message) from exc


@router.get("/brands", response_model=list[VehicleBrandOut])
def list_brands(
    search: str | None = None,
    include_inactive: bool = False,
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_inactive_access(include_inactive, current_user)
    query = db.query(VehicleBrand)
    if not include_inactive:
        query = query.filter(VehicleBrand.is_active.is_(True))
    if search and search.strip():
        query = query.filter(VehicleBrand.normalized_name.contains(normalize_catalog_name(search)))
    return [brand_out(brand) for brand in query.order_by(VehicleBrand.name).limit(limit).all()]


@router.get("/brands/{brand_id}/models", response_model=list[VehicleModelOut])
def list_models(
    brand_id: int,
    search: str | None = None,
    include_inactive: bool = False,
    limit: int = Query(default=300, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_inactive_access(include_inactive, current_user)
    brand = db.get(VehicleBrand, brand_id)
    if not brand or (not include_inactive and not brand.is_active):
        raise HTTPException(status_code=404, detail="Vehicle brand not found.")

    query = db.query(VehicleModel).filter(VehicleModel.brand_id == brand_id)
    if not include_inactive:
        query = query.filter(VehicleModel.is_active.is_(True))
    if search and search.strip():
        query = query.filter(VehicleModel.normalized_name.contains(normalize_catalog_name(search)))
    return [model_out(model) for model in query.order_by(VehicleModel.name).limit(limit).all()]


@router.post(
    "/brands",
    response_model=VehicleBrandOut,
    status_code=201,
    dependencies=[Depends(require_roles(UserRole.admin))],
)
def create_brand(payload: VehicleBrandCreate, db: Session = Depends(get_db)):
    brand = VehicleBrand(
        name=payload.name,
        normalized_name=normalize_catalog_name(payload.name),
        is_active=payload.is_active,
    )
    db.add(brand)
    commit_catalog_change(db, f"Vehicle brand '{payload.name}' already exists.")
    db.refresh(brand)
    return brand_out(brand)


@router.put(
    "/brands/{brand_id}",
    response_model=VehicleBrandOut,
    dependencies=[Depends(require_roles(UserRole.admin))],
)
def update_brand(brand_id: int, payload: VehicleBrandUpdate, db: Session = Depends(get_db)):
    brand = db.get(VehicleBrand, brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Vehicle brand not found.")
    brand.name = payload.name
    brand.normalized_name = normalize_catalog_name(payload.name)
    brand.is_active = payload.is_active
    commit_catalog_change(db, f"Vehicle brand '{payload.name}' already exists.")
    db.refresh(brand)
    return brand_out(brand)


@router.delete(
    "/brands/{brand_id}",
    response_model=VehicleBrandOut,
    dependencies=[Depends(require_roles(UserRole.admin))],
)
def deactivate_brand(brand_id: int, db: Session = Depends(get_db)):
    brand = db.get(VehicleBrand, brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Vehicle brand not found.")
    brand.is_active = False
    db.commit()
    db.refresh(brand)
    return brand_out(brand)


@router.post(
    "/models",
    response_model=VehicleModelOut,
    status_code=201,
    dependencies=[Depends(require_roles(UserRole.admin))],
)
def create_model(payload: VehicleModelCreate, db: Session = Depends(get_db)):
    if not db.get(VehicleBrand, payload.brand_id):
        raise HTTPException(status_code=404, detail="Vehicle brand not found.")
    model = VehicleModel(
        brand_id=payload.brand_id,
        name=payload.name,
        normalized_name=normalize_catalog_name(payload.name),
        is_active=payload.is_active,
    )
    db.add(model)
    commit_catalog_change(db, f"Vehicle model '{payload.name}' already exists for this brand.")
    db.refresh(model)
    return model_out(model)


@router.put(
    "/models/{model_id}",
    response_model=VehicleModelOut,
    dependencies=[Depends(require_roles(UserRole.admin))],
)
def update_model(model_id: int, payload: VehicleModelUpdate, db: Session = Depends(get_db)):
    model = db.get(VehicleModel, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Vehicle model not found.")
    if not db.get(VehicleBrand, payload.brand_id):
        raise HTTPException(status_code=404, detail="Vehicle brand not found.")
    if model.brand_id != payload.brand_id and db.query(Vehicle).filter(Vehicle.model_id == model.id).first():
        raise HTTPException(status_code=409, detail="A model already used by Vehicles cannot be moved to another brand.")
    model.brand_id = payload.brand_id
    model.name = payload.name
    model.normalized_name = normalize_catalog_name(payload.name)
    model.is_active = payload.is_active
    commit_catalog_change(db, f"Vehicle model '{payload.name}' already exists for this brand.")
    db.refresh(model)
    return model_out(model)


@router.delete(
    "/models/{model_id}",
    response_model=VehicleModelOut,
    dependencies=[Depends(require_roles(UserRole.admin))],
)
def deactivate_model(model_id: int, db: Session = Depends(get_db)):
    model = db.get(VehicleModel, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Vehicle model not found.")
    model.is_active = False
    db.commit()
    db.refresh(model)
    return model_out(model)
