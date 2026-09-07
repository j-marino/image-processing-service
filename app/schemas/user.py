from pydantic import BaseModel, Field
from pydantic import EmailStr
from app.schemas.token import Token
from sqlmodel import Field, Column, String

# request
class UserCreate(BaseModel):
    username: str = Field(min_length=4, sa_column_kwargs={"index": True, "unique": True})
    email: EmailStr = Field(sa_column_kwargs={"index": True, "unique": True})
    password: str = Field(min_length=8)


class UserLogin(BaseModel):
    username: str
    password: str


class UserPublic(BaseModel):
    username: str
    email: EmailStr

    
class LoginResponse(BaseModel):
    user: UserPublic
    token: Token



    