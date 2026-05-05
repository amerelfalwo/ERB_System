from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.domain import Party
from app.schemas.party import PartyCreate, PartyOut
from app.services.payments import get_party_balance

router = APIRouter(prefix="/parties", tags=["parties"])


@router.post("", response_model=PartyOut)
def create_party(data: PartyCreate, db: Session = Depends(get_db)):
    party = Party(name=data.name, party_type=data.party_type)
    db.add(party)
    db.commit()
    db.refresh(party)
    return party


@router.get("", response_model=list[PartyOut])
def list_parties(db: Session = Depends(get_db)):
    return db.execute(select(Party)).scalars().all()


@router.get("/{party_id}/balance")
def party_balance(party_id: int, db: Session = Depends(get_db)):
    balance = get_party_balance(db, party_id)
    return {"party_id": party_id, "balance": balance}
