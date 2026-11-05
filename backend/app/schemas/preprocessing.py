import math
from typing import Literal

from pydantic import BaseModel, Field, model_validator


ImputationMethod = Literal["mean", "median", "mode", "constant", "leave_missing"]


class ImputationColumnRequest(BaseModel):
    column: str = Field(min_length=1, max_length=200)
    method: ImputationMethod
    constant_value: str | int | float | bool | None = None

    @model_validator(mode="after")
    def validate_constant(self):
        if self.method == "constant" and self.constant_value is None:
            raise ValueError("constant_value is required for constant imputation")
        if self.method == "constant" and isinstance(self.constant_value, str):
            if not self.constant_value.strip():
                raise ValueError("constant_value must not be blank")
        if (
            self.method == "constant"
            and isinstance(self.constant_value, float)
            and not math.isfinite(self.constant_value)
        ):
            raise ValueError("constant_value must be finite")
        if self.method != "constant" and self.constant_value is not None:
            raise ValueError("constant_value is only valid with the constant method")
        return self


class ImputationPreviewRequest(BaseModel):
    split_column: str = Field(min_length=1, max_length=200)
    training_partition: str = Field(default="train", min_length=1, max_length=100)
    split_operation_id: str | None = Field(default=None, max_length=100)
    columns: list[ImputationColumnRequest] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_columns(self):
        names = [column.column for column in self.columns]
        if len(names) != len(set(names)):
            raise ValueError("Imputation columns must be unique")
        return self


class ImputationExecuteRequest(ImputationPreviewRequest):
    preview_token: str = Field(min_length=64, max_length=64)
    confirmed: bool = False


class ImputationPreviewResponse(BaseModel):
    preview_token: str
    source_file_sha256: str
    split_column: str
    training_partition: str
    fit_row_count: int
    strategies: list[dict]
    missing_counts_before: dict[str, int]
    missing_counts_after: dict[str, int]
    expected_row_count: int
    expected_column_count: int
    protected_columns: list[str]
    confirmation_required: bool = True
