import io
import numpy as np
from PIL import Image, ImageOps
from app.schemas.images import Crop, Resize, Rotate, Filters, Transformations, Format

CORRUPTION_INVERSION_CHANCE = 0.6

async def get_PIL_image(image_bytes: bytes) -> Image.Image:
    buffer = io.BytesIO(image_bytes)
    image = Image.open(buffer)
    return image


async def bytes_to_image(image_bytes: bytes) -> Image.Image:
    buffer = io.BytesIO(image_bytes)
    image = Image.open(buffer)
    return image


async def image_to_bytes(image: Image.Image, output_format: str) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=output_format)
    return buffer.getvalue()


async def pil_to_buffer(image: Image.Image, image_format: str) -> io.BytesIO:
    buffer = io.BytesIO()
    image.save(buffer, format=image_format)
    buffer.seek(0) # rewind so upload_fileobj reads from the start, not the end
    return buffer


async def crop_image(image: Image.Image, crop: Crop) -> Image.Image:
    return image.crop((crop.x, crop.y, crop.width + crop.x, crop.height + crop.y))


async def resize_image(image: Image.Image, resize: Resize) -> Image.Image:
    return image.resize((resize.width, resize.height))


async def rotate_image(image: Image.Image, rotate: Rotate) -> Image.Image:
    return image.rotate(rotate.degrees, expand=1)


async def apply_filters(image: Image.Image, filters: Filters) -> Image.Image:
    if filters.grey_scale:
        image = ImageOps.grayscale(image)

    if filters.solarize:
        image = ImageOps.solarize(image)

    if filters.chromatic_aberration:
        image = chromatic_aberration(image)

    return image


def chromatic_aberration(image: Image.Image, intensity: float = 0.15) -> Image.Image:
    img = image.convert("RGB")
    arr = np.array(img)
    h, w, _ = arr.shape
    
    # chromatic aberration
    shift = int(w * 0.02)
    arr[:, :, 0] = np.roll(arr[:, :, 0], shift, axis=1)
    arr[:, :, 2] = np.roll(arr[:, :, 2], -shift, axis=1)

    return Image.fromarray(arr)



async def apply_transformations(
    image: Image.Image, transformations: Transformations) -> Image.Image:

    if transformations.crop:
        image = await crop_image(image, transformations.crop)

    if transformations.resize:
        image = await resize_image(image, transformations.resize)

    if transformations.rotate:
        image = await rotate_image(image, transformations.rotate)

    if transformations.filters:
        image = await apply_filters(image, transformations.filters)

    return image
