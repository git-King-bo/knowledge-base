from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.sqlite import KnowledgeRepository
from app.schemas.documents import Document, DocumentCreate, DocumentUpdate

router = APIRouter()


@router.get("", response_model=list[Document])
def list_documents(
    q: str | None = Query(default=None),
    category_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[Document]:
    return KnowledgeRepository(db).list_documents(q=q, category_id=category_id)


@router.post("", response_model=Document, status_code=status.HTTP_201_CREATED)
def create_document(payload: DocumentCreate, db: Session = Depends(get_db)) -> Document:
    return KnowledgeRepository(db).create_document(payload)


@router.get("/{document_id}", response_model=Document)
def get_document(document_id: str, db: Session = Depends(get_db)) -> Document:
    document = KnowledgeRepository(db).get_document(document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


@router.put("/{document_id}", response_model=Document)
def update_document(
    document_id: str,
    payload: DocumentUpdate,
    db: Session = Depends(get_db),
) -> Document:
    document = KnowledgeRepository(db).update_document(document_id, payload)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str, db: Session = Depends(get_db)) -> None:
    deleted = KnowledgeRepository(db).delete_document(document_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
