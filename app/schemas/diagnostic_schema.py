from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DiagnosticRequest(BaseModel):
    business_name: str = Field(..., min_length=1, max_length=255)
    data: dict[str, Any] = Field(default_factory=dict)


class DiagnosticResponse(BaseModel):
    diagnostic_id: int
    report_id: int
    status: str
    message: str
    llm_response: str

    model_config = ConfigDict(from_attributes=True)
