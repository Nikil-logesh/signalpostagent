from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Availability = Literal[
    "available",
    "not_available",
    "blocked",
    "not_applicable",
    "ambiguous",
    "failed",
]


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source_url: str
    source_class: str
    retrieved_at: str
    content_sha256: str | None = None
    claim_span: str | None = None
    effective_at: str | None = None
    reporting_period: str | None = None


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    value: Any | None = None
    availability: Availability
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("evidence_ids")
    @classmethod
    def evidence_is_required_for_available_claims(cls, value: list[str], info):
        if info.data.get("availability") == "available" and not value:
            raise ValueError("available claims require evidence_ids")
        return value


class RunMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    started_at: str
    completed_at: str
    terminal_status: Literal["completed", "partial", "failed"]


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    old: Any | None = None
    new: Any | None = None
    detected_at: str
    material: bool = False


class ErrorItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    message: str
    availability: Literal["blocked", "failed", "not_available"] = "failed"


class Operations(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requests: int = Field(ge=0)
    runtime_ms: int = Field(ge=0)
    third_party_cost_usd: float = Field(default=0.0, ge=0.0)
    llm_requests: int = Field(default=0, ge=0)
    llm_input_tokens: int = Field(default=0, ge=0)
    llm_output_tokens: int = Field(default=0, ge=0)


class CompanyEnvelope(BaseModel):
    """Pydantic representation of the kit's terminal JSONL contract."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "signalpost.profile.v1"
    organisation_number: str = Field(pattern=r"^\d{9}$")
    run: RunMetadata
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    changes: list[Change] = Field(default_factory=list)
    errors: list[ErrorItem] = Field(default_factory=list)
    operations: Operations

    @field_validator("evidence")
    @classmethod
    def evidence_ids_are_unique(cls, value: list[Evidence]) -> list[Evidence]:
        ids = [item.id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence IDs must be unique")
        return value

    def deterministic_json(self) -> str:
        return self.model_dump_json(exclude_none=True, by_alias=True, indent=None)
