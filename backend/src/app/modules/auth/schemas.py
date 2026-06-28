from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AuthenticatedTeamMembership(BaseModel):
    team_id: UUID
    role: str


class AuthenticatedProjectMembership(BaseModel):
    project_id: UUID
    role: str


class MemberTeamMembershipResponse(BaseModel):
    team_id: UUID
    role: str


class MemberProjectMembershipResponse(BaseModel):
    project_id: UUID
    role: str


class AuthenticatedUser(BaseModel):
    id: UUID
    org_id: UUID
    team_id: UUID | None = None
    email: EmailStr
    role: str
    permissions: list[str] = []
    team_memberships: list[AuthenticatedTeamMembership] = []
    project_memberships: list[AuthenticatedProjectMembership] = []


class UserLabel(BaseModel):
    id: UUID
    display_name: str | None
    email: str | None


class CreateInviteRequest(BaseModel):
    email: EmailStr
    role: str = Field(
        default="org_member",
        pattern="^(org_owner|org_admin|org_viewer|org_member)$",
    )
    team_id: UUID | None = None
    team_role: str | None = Field(default=None, pattern="^(team_admin|team_member)$")
    project_id: UUID | None = None
    project_role: str | None = Field(
        default=None,
        pattern="^(project_admin|project_member)$",
    )


class CreateMemberRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    name: str | None = Field(default=None, max_length=255)
    role: str = Field(
        default="org_viewer",
        pattern="^(org_owner|org_admin|org_viewer|org_member)$",
    )
    team_id: UUID | None = None
    team_role: str | None = Field(default=None, pattern="^(team_admin|team_member)$")
    project_id: UUID | None = None
    project_role: str | None = Field(
        default=None,
        pattern="^(project_admin|project_member)$",
    )

    @field_validator("password")
    @classmethod
    def validate_password_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("password must be at most 72 UTF-8 bytes")
        return value


class InviteResponse(BaseModel):
    id: UUID
    org_id: UUID
    team_id: UUID | None
    project_id: UUID | None
    email: EmailStr
    role: str
    team_role: str | None
    project_role: str | None
    status: str
    expires_at: datetime
    accepted_at: datetime | None
    created_at: datetime
    invite_url: str | None = None


class InvitePreviewResponse(BaseModel):
    email: EmailStr
    organization_name: str
    role: str
    team_name: str | None
    team_role: str | None
    project_name: str | None
    project_role: str | None
    status: str
    expires_at: datetime


class MemberResponse(BaseModel):
    user_id: UUID
    email: EmailStr
    name: str | None
    role: str
    status: str
    created_at: datetime
    team_memberships: list[MemberTeamMembershipResponse] = []
    project_memberships: list[MemberProjectMembershipResponse] = []
    effective_permissions: list[str] = []


class MemberOptionResponse(BaseModel):
    user_id: UUID
    email: EmailStr
    name: str | None


class UpdateMemberRequest(BaseModel):
    role: str = Field(pattern="^(org_owner|org_admin|org_viewer|org_member)$")


class UpdateMemberStatusRequest(BaseModel):
    status: str = Field(pattern="^(active|inactive)$")


class TeamMemberResponse(BaseModel):
    user_id: UUID
    email: EmailStr
    name: str | None
    org_role: str
    team_role: str
    created_at: datetime


class ProjectMemberResponse(BaseModel):
    user_id: UUID
    email: EmailStr
    name: str | None
    org_role: str
    project_role: str
    created_at: datetime


class UpsertTeamMemberRequest(BaseModel):
    user_id: UUID
    role: str = Field(default="team_member", pattern="^(team_admin|team_member)$")


class UpdateTeamMemberRequest(BaseModel):
    role: str = Field(pattern="^(team_admin|team_member)$")


class UpsertProjectMemberRequest(BaseModel):
    user_id: UUID
    role: str = Field(
        default="project_member",
        pattern="^(project_admin|project_member)$",
    )


class UpdateProjectMemberRequest(BaseModel):
    role: str = Field(pattern="^(project_admin|project_member)$")


class AcceptInviteRequest(BaseModel):
    token: str = Field(min_length=1)
    name: str | None = Field(default=None, max_length=255)
    password: str = Field(min_length=8, max_length=72)

    @field_validator("password")
    @classmethod
    def validate_password_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("password must be at most 72 UTF-8 bytes")
        return value


