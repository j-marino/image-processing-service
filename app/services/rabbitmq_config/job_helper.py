from fastapi import HTTPException
from sqlmodel import select
from uuid import UUID
from app.models.image import TransformJob
from app.dependencies import SessionDep


async def get_job(session: SessionDep, job_id: str, user_id: int) -> TransformJob:
    try:
        job_id = UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Job not found")
    
    result = await session.exec(select(TransformJob).where(TransformJob.job_id == job_id))
    job = result.first()
    if not job:
        raise HTTPException(status_code=404, detail="Job does not exist")

    if job.user_id != user_id:
        raise HTTPException(status_code=403, detail="You do not have permission to access this job")

    return job

