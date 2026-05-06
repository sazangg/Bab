from pydantic import BaseModel, EmailStr, Field


class SetupStatusResponse(BaseModel):
    setup_required: bool


class CreateFirstAdminRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12)
    organization_name: str = Field(min_length=1, max_length=255)


class CreateFirstAdminResponse(BaseModel):
    email: EmailStr
    organization_name: str
    role: str
