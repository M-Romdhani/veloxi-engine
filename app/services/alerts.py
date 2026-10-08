"""Alert emission for opportunity-change and source-health events."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Alert, AlertType, Opportunity, Source


def emit_alert(
    session: Session,
    type_: AlertType | str,
    message: str,
    *,
    opportunity: Opportunity | None = None,
    source: Source | None = None,
    payload: dict | None = None,
) -> Alert:
    alert = Alert(
        type=type_.value if isinstance(type_, AlertType) else str(type_),
        message=message,
        opportunity_id=opportunity.id if opportunity is not None else None,
        source_id=source.id if source is not None else None,
        payload=payload or {},
    )
    session.add(alert)
    return alert
