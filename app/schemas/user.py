from pydantic import BaseModel
from typing import Optional


class UserCreate(BaseModel):
    username: str
    password: str
    company_name: str
    full_name: str


class UserOut(BaseModel):
    id: int
    username: str

    class Config:
        from_attributes = True


class TenantInfo(BaseModel):
    id: int
    company_name: str
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    default_footer_text: Optional[str] = None

    class Config:
        from_attributes = True


class UserProfile(BaseModel):
    id: int
    username: str
    role: str
    tenant: TenantInfo

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str
