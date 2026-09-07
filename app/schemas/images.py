import uuid
from pydantic import BaseModel, Field

from typing import Literal
from ..models.image import Image


MAX_DIMENSION = 4096


class ImageResponse(BaseModel):
    upload_status: bool
    details: Image
    message: str | None = None

class Resize(BaseModel):
    width: int = Field(gt=0, le=MAX_DIMENSION)
    height: int = Field(gt=0, le=MAX_DIMENSION)


class Crop(BaseModel):
    width: int = Field(gt=0, le=MAX_DIMENSION)
    height: int = Field(gt=0, le=MAX_DIMENSION)
    x: int = Field(ge=0, le=MAX_DIMENSION)
    y: int = Field(ge=0, le=MAX_DIMENSION)


class Rotate(BaseModel):
    degrees: int = Field(ge=-360, le=360)


class Format(BaseModel):
    target_format: Literal["jpeg", "png", "jpg"]


class Filters(BaseModel):
    grey_scale: bool = False
    solarize: bool = False
    chromatic_aberration: bool = False


class Transformations(BaseModel):
    resize: Resize | None = None
    crop: Crop | None = None
    rotate: Rotate | None = None
    image_format: Format | None = None
    filters: Filters | None = None
    image_name: str | None = Field(default=None, min_length=4, max_length=12)


class ImageRead(BaseModel): 
    id: uuid.UUID
    name: str
    size: int
    content_type: str
    url: str
    uploaded_by: int
