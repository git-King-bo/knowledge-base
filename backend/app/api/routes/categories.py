from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.sqlite import KnowledgeRepository
from app.schemas.documents import Category

router = APIRouter()


@router.get("", response_model=list[Category])
def list_categories(db: Session = Depends(get_db)) -> list[Category]:
    return KnowledgeRepository(db).list_categories()
