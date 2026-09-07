from typing import Annotated
from datetime import timedelta
from fastapi import Depends, HTTPException, Request, status, APIRouter, Response

from fastapi.security import OAuth2PasswordRequestForm
from app.services.slowapi.slowapi_limiter import limiter
from app.schemas.token import Token
from app.services.auth.auth import authenticate_user, create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES
from app.dependencies import SessionDep


router = APIRouter()


@router.post("/token")
@limiter.limit("10/minute")
async def login_for_access_token(
    request: Request,
    response: Response,
    session: SessionDep,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    user = await authenticate_user(session, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return Token(access_token=access_token, token_type="bearer")