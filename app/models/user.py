from sqlmodel import Field, SQLModel
from pydantic import EmailStr


class User(SQLModel, table=True):
    __tablename__ = "users"
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    email: EmailStr = Field(index=True, unique=True)
    hashed_password: str = Field(nullable=False)
    disabled: bool = Field(default=False) # defaults to enabled user