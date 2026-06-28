from pydantic import BaseModel
from typing import Optional


class TenantRegistration(BaseModel):
    full_name: str
    company_name: str
    username: str
    password: str


class UserCreate(BaseModel):
    username: str
    password: str
    company_name: str
    full_name: str


class UserOut(BaseModel):
    id: int
    username: str
    full_name: Optional[str] = None
    role: str

    class Config:
        from_attributes = True


class TenantInfo(BaseModel):
    id: int
    company_name: str
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    default_footer_text: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    tax_number: Optional[str] = None
    print_notes: Optional[str] = None
    store_name: Optional[str] = None

    class Config:
        from_attributes = True


class UserProfile(BaseModel):
    id: int
    username: str
    full_name: Optional[str] = None
    role: str
    tenant: TenantInfo

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str
