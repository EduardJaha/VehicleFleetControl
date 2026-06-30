from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import create_access_token, get_current_user, hash_password, require_roles, verify_password
from app.db.session import get_db
from app.models import User
from app.schemas import FirstAdminCreate, LoginRequest, TokenOut, UserCreate, UserOut, UserRole

router = APIRouter()


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=UserRole(user.role),
        is_active=user.is_active,
    )


def find_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email.strip().lower()).first()


def create_user_record(db: Session, payload: UserCreate | FirstAdminCreate, role: UserRole | None = None) -> User:
    user = User(
        email=payload.email.strip().lower(),
        full_name=payload.full_name.strip(),
        hashed_password=hash_password(payload.password),
        role=(role or getattr(payload, "role", UserRole.viewer)).value,
        is_active=getattr(payload, "is_active", True),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A user with this email already exists.") from exc
    db.refresh(user)
    return user


@router.post("/register", response_model=TokenOut, status_code=201)
def register_first_admin(payload: FirstAdminCreate, db: Session = Depends(get_db)):
    if db.query(User).first():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Initial admin already exists. Ask an Admin to create additional users.")
    user = create_user_record(db, payload, UserRole.admin)
    return TokenOut(access_token=create_access_token(user.id), user=user_out(user))


@router.post("/login", response_model=TokenOut)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = find_user_by_email(db, payload.email)
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive.")
    return TokenOut(access_token=create_access_token(user.id), user=user_out(user))


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return user_out(current_user)


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(payload: UserCreate, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.admin))):
    return user_out(create_user_record(db, payload))
