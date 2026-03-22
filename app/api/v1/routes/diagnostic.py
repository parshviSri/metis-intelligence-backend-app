from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, status

from app.core.database import get_db
from app.repositories.diagnostic_repo import create_diagnostic, create_report
from app.schemas.diagnostic_schema import DiagnosticRequest, DiagnosticResponse
from app.services.llm_service import generate_report

router = APIRouter(prefix="/diagnostic", tags=["Diagnostic"])


@router.post("/submit", response_model=DiagnosticResponse, status_code=status.HTTP_201_CREATED)
def submit_diagnostic(payload: DiagnosticRequest, db: Session = Depends(get_db)) -> DiagnosticResponse:
    diagnostic = create_diagnostic(db=db, raw_input=payload.model_dump())
    llm_output = generate_report(payload.model_dump())
    report = create_report(db=db, diagnostic_id=diagnostic.id, llm_response=llm_output)

    return DiagnosticResponse(
        diagnostic_id=diagnostic.id,
        report_id=report.id,
        status="submitted",
        message="Diagnostic submitted successfully.",
        llm_response=report.llm_response,
    )
