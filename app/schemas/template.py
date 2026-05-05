from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict


class PrintTemplateCreate(BaseModel):
    name: str
    html_content: str
    settings: Optional[Dict[str, Any]] = None


class PrintTemplateUpdate(BaseModel):
    name: Optional[str] = None
    html_content: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None


class PrintTemplateOut(BaseModel):
    id: int
    name: str
    html_content: str
    settings: Optional[Dict[str, Any]]

    model_config = ConfigDict(from_attributes=True)


class PrintPreviewOut(BaseModel):
    html: str
