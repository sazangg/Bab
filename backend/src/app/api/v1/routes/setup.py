from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.setup import facade
from app.modules.setup.schemas import (
    CreateFirstAdminRequest,
    CreateFirstAdminResponse,
    SetupStatusResponse,
)
from app.modules.setup.service import SetupAlreadyCompletedError

router = APIRouter(prefix="/setup", tags=["setup"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("/status")
async def get_setup_status(db: DatabaseSession) -> SetupStatusResponse:
    return SetupStatusResponse(setup_required=await facade.setup_required(db))


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_first_admin(
    payload: CreateFirstAdminRequest,
    db: DatabaseSession,
) -> CreateFirstAdminResponse:
    try:
        return await facade.create_first_admin(payload, db)
    except SetupAlreadyCompletedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="setup already completed",
        ) from exc
