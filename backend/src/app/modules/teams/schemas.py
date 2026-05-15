from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateTeamRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)


class UpdateTeamRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None


class TeamResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    name: str
    slug: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
