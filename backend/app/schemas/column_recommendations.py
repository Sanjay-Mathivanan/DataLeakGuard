from typing import Literal

from pydantic import BaseModel


class ColumnRecommendationCandidate(BaseModel):
    column_name: str
    role: Literal["target", "entity", "split", "timestamp"]
    score: int
    confidence: Literal["high", "medium", "low", "not_recommended"]
    explanation: str
    supporting_signals: list[str]
    warnings: list[str]
    profile: dict


class ColumnRoleRecommendations(BaseModel):
    recommendation: ColumnRecommendationCandidate | None
    candidates: list[ColumnRecommendationCandidate]
    warnings: list[str]


class ColumnRecommendationsResponse(BaseModel):
    profiled_column_count: int
    sample_count: int | None
    roles: dict[
        Literal["target", "entity", "split", "timestamp"],
        ColumnRoleRecommendations,
    ]
    limitations: list[str]
