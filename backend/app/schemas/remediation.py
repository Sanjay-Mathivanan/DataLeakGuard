from typing import Literal

from pydantic import BaseModel, Field, model_validator


RemediationActionName = Literal[
    "exact_duplicate_keep_first",
    "quarantine_evidenced_rows",
    "rebuild_group_split",
    "exclude_target_features",
    "rebuild_chronological_split",
    "exclude_contaminated_copies",
    "review_only",
]


class RemediationActionRequest(BaseModel):
    action: RemediationActionName
    selection_mode: Literal["explicit", "all_eligible"] = "explicit"
    finding_ids: list[str] = Field(default_factory=list, max_length=500)
    # Required for the server-side all-eligible selection mode.
    finding_type: str | None = Field(default=None, max_length=100)
    entity_column: str | None = Field(default=None, max_length=200)
    entity_columns: list[str] = Field(default_factory=list, max_length=20)
    split_column: str | None = Field(default=None, max_length=200)
    target_column: str | None = Field(default=None, max_length=200)
    feature_columns: list[str] = Field(default_factory=list, max_length=200)
    time_column: str | None = Field(default=None, max_length=200)
    cutoff: str | None = Field(default=None, max_length=100)
    retained_partition: str | None = Field(default=None, max_length=100)
    test_ratio: float | None = Field(default=None, gt=0, lt=1)
    random_seed: int | None = Field(default=None, ge=-(2**31), le=(2**31) - 1)
    train_label: str = Field(default="train", min_length=1, max_length=100)
    test_label: str = Field(default="test", min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_selection(self):
        if self.selection_mode == "explicit":
            if not self.finding_ids:
                raise ValueError("Explicit remediation selection requires finding_ids")
            if any(not finding_id.strip() for finding_id in self.finding_ids):
                raise ValueError("finding_ids must not contain blank identifiers")
            if len(set(self.finding_ids)) != len(self.finding_ids):
                raise ValueError("finding_ids must be unique within an action")
        elif not self.finding_type:
            raise ValueError("all_eligible selection requires finding_type")
        if self.action == "rebuild_group_split":
            normalized_entities = [
                value.strip()
                for value in self.entity_columns
                if isinstance(value, str) and value.strip()
            ]
            if (
                len(normalized_entities) != len(self.entity_columns)
                or len(set(normalized_entities)) != len(normalized_entities)
            ):
                raise ValueError("entity_columns must contain unique, non-empty names")
            if self.entity_column and normalized_entities:
                raise ValueError("Provide entity_column or entity_columns, not both")
            if not self.entity_column and not normalized_entities:
                raise ValueError("Group-aware split rebuilding requires an entity key")
            if not self.split_column:
                raise ValueError("Group-aware split rebuilding requires split_column")
            if self.test_ratio is None or self.random_seed is None:
                raise ValueError("Group-aware split rebuilding requires test_ratio and random_seed")
        elif self.action == "exclude_target_features":
            if not self.target_column or (
                not self.feature_columns and self.selection_mode != "all_eligible"
            ):
                raise ValueError("Target feature exclusion requires target_column and feature_columns")
        elif self.action == "rebuild_chronological_split":
            if not self.time_column or not self.split_column or not self.cutoff:
                raise ValueError(
                    "Chronological split rebuilding requires time_column, split_column, and cutoff"
                )
        elif self.action == "exclude_contaminated_copies":
            if not self.split_column or not self.retained_partition:
                raise ValueError(
                    "Contamination exclusion requires split_column and retained_partition"
                )
        if self.train_label.strip().casefold() == self.test_label.strip().casefold():
            raise ValueError("train_label and test_label must be different")
        return self


class RemediationPreviewRequest(BaseModel):
    actions: list[RemediationActionRequest] = Field(min_length=1, max_length=5)


class RemediationExecuteRequest(BaseModel):
    preview_token: str = Field(min_length=64, max_length=64)
    confirmed: bool


class RemediationCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)
