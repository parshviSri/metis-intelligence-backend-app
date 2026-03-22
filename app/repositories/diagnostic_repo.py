from sqlalchemy.orm import Session

from app.models.diagnostic import Diagnostic, Report


def create_diagnostic(db: Session, raw_input: dict) -> Diagnostic:
    diagnostic = Diagnostic(raw_input_json=raw_input)
    db.add(diagnostic)
    db.commit()
    db.refresh(diagnostic)
    return diagnostic


def create_report(db: Session, diagnostic_id: int, llm_response: str) -> Report:
    report = Report(diagnostic_id=diagnostic_id, llm_response=llm_response)
    db.add(report)
    db.commit()
    db.refresh(report)
    return report
