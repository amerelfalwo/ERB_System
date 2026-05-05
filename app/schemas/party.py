from pydantic import BaseModel, ConfigDict

from app.models.domain import PartyType


class PartyBase(BaseModel):
    name: str
    party_type: PartyType


class PartyCreate(PartyBase):
    pass


class PartyOut(PartyBase):
    id: int

    model_config = ConfigDict(from_attributes=True)
