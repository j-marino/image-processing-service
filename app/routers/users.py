import asyncio
from datetime import timedelta
from fastapi import APIRouter, HTTPException, Request, Response
from sqlmodel import select

from app.services.slowapi.slowapi_limiter import limiter
from app.models.user import User
from app.services.auth.auth import ACCESS_TOKEN_EXPIRE_MINUTES, authenticate_user, create_access_token, get_password_hash
from app.schemas.user import UserCreate, LoginResponse, UserLogin, UserPublic
from app.schemas.token import Token
from app.dependencies import SessionDep

router = APIRouter()

@router.post("/register", response_model=LoginResponse)
@limiter.limit("15/minute")
async def register_user(request: Request, response: Response, user: UserCreate, session: SessionDep):
    existing = await session.exec(select(User).where(User.username == user.username))
    if existing.first():
        raise HTTPException(status_code=400, detail="Username already registered")

    hashed_password = await asyncio.to_thread(get_password_hash, user.password)
    new_user = User(username=user.username, email=user.email, hashed_password=hashed_password)
    session.add(new_user)
    await session.commit()
    await session.refresh(new_user)

    access_token = create_access_token(
        data={"sub": new_user.username},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return LoginResponse(
        user=UserPublic(username=new_user.username, email=new_user.email),
        token=Token(access_token=access_token, token_type="bearer"),
    )


@router.post("/login", response_model=LoginResponse)
@limiter.limit("15/minute")
async def login_user(request: Request, response: Response, user: UserLogin, session: SessionDep):
    db_user = await authenticate_user(session, user.username, user.password)
    if not db_user:
        raise HTTPException(status_code=400, detail="Invalid username or password")
    access_token = create_access_token(
        data={"sub": db_user.username},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return LoginResponse(
                        user=UserPublic(username=db_user.username, email=db_user.email), 
                        token=Token(access_token=access_token, token_type="bearer")
                    )