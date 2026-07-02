from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from .. import models, database, schemas
from ..security import hash_password, verify_password, create_access_token

router = APIRouter()

# New users start with 100 credits so they can immediately submit jobs.
STARTER_CREDITS = 100.0


@router.post("/register", response_model=schemas.UserResponse)
def register_user(user: schemas.UserCreate, db: Session = Depends(database.get_db)):
    # 1. Check email uniqueness
    if db.query(models.User).filter(models.User.email == user.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    # 2. Hash the password before storing.
    #    bcrypt produces a string like "$2b$12$..." — the original is unrecoverable.
    new_user = models.User(
        email=user.email,
        password=hash_password(user.password),
        role=user.role,
        credits=STARTER_CREDITS,
        created_at=datetime.now(timezone.utc),
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@router.post("/login", response_model=schemas.LoginResponse)
def login_user(user_credentials: schemas.UserLogin, db: Session = Depends(database.get_db)):
    # 1. Find user by email
    user = db.query(models.User).filter(models.User.email == user_credentials.email).first()

    # 2. Verify password against the stored bcrypt hash.
    #    We use a generic error message — never tell the caller which field was wrong.
    if not user or not verify_password(user_credentials.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # 3. Issue a JWT. The frontend stores this and sends it as
    #    "Authorization: Bearer <token>" on every subsequent request.
    token = create_access_token(user_id=user.id, role=user.role)

    return schemas.LoginResponse(
        access_token=token,
        token_type="bearer",
        user=schemas.UserResponse(
            id=user.id,
            email=user.email,
            role=user.role,
            credits=user.credits,
        ),
    )


@router.get("/wallet/{user_id}")
def get_wallet_balance(user_id: int, db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_id": user.id, "credits": user.credits, "role": user.role}
