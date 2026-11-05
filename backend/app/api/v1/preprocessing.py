"""Owner-scoped preprocessing preview and execution endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.identity import get_current_user
from app.db import models
from app.db.session import get_db
from app.schemas.preprocessing import (
    ImputationExecuteRequest,
    ImputationPreviewRequest,
)
from app.services.preprocessing_service import (
    execute_train_only_imputation,
    preview_train_only_imputation,
)

router = APIRouter()


def _owned_dataset(
    dataset_id: str,
    db: Session,
    user: models.User,
) -> models.Dataset:
    dataset = db.query(models.Dataset).filter(
        models.Dataset.id == dataset_id,
        models.Dataset.owner_user_id == user.id,
    ).first()
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset


@router.post(
    "/datasets/{dataset_id}/preprocessing/imputation/preview",
    status_code=status.HTTP_200_OK,
)
def preview_imputation(
    dataset_id: str,
    request: ImputationPreviewRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    dataset = _owned_dataset(dataset_id, db, user)
    return preview_train_only_imputation(dataset=dataset, request=request, db=db)


@router.post(
    "/datasets/{dataset_id}/preprocessing/imputation/execute",
    status_code=status.HTTP_201_CREATED,
)
def execute_imputation(
    dataset_id: str,
    request: ImputationExecuteRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    dataset = _owned_dataset(dataset_id, db, user)
    return execute_train_only_imputation(
        dataset=dataset,
        request=request,
        preview_token=request.preview_token,
        confirmed=request.confirmed,
        db=db,
        user=user,
    )
