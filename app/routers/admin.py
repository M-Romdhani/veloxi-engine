"""Admin API (token-guarded): sources, ingestion, approval queue, logs, alerts."""
from __future__ import annotations

from datetime import timedelta

from dateutil import parser as dtparser
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..ingest.runner import ingest_all, ingest_source
from ..models import (
    Alert,
    CareerReport,
    IngestionLog,
    Opportunity,
    RawOpportunity,
    RawStatus,
    Source,
    SourceType,
    ValidationLog,
    utcnow,
)
from ..pipeline.promote import promote_raw_to_opportunity
from ..pipeline.verify_source import probe_source
from ..schemas import CareerAnalyzeIn, ManualOpportunityIn, RejectIn, SourceIn, SourceUpdate
from ..seed import load_seed
from ..services import career as career_service
from ..services import cv_extract

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# --------------------------- serializers --------------------------- #
def _source_dict(s: Source) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "type": s.type,
        "url": s.url,
        "config": s.config,
        "status": s.status,
        "isEnabled": s.is_enabled,
        "defaultProvider": s.default_provider,
        "healthScore": s.health_score,
        "consecutiveFailures": s.consecutive_failures,
        "lastProbedAt": s.last_probed_at.isoformat() if s.last_probed_at else None,
        "lastIngestedAt": s.last_ingested_at.isoformat() if s.last_ingested_at else None,
    }


def _raw_dict(r: RawOpportunity) -> dict:
    return {
        "id": r.id,
        "sourceId": r.source_id,
        "title": r.title,
        "url": r.url,
        "provider": r.provider,
        "suggestedCategory": r.suggested_category,
        "status": r.status,
        "createdAt": r.created_at.isoformat() if r.created_at else None,
    }


def _ingest_log_dict(log: IngestionLog) -> dict:
    return {
        "id": log.id,
        "sourceId": log.source_id,
        "startedAt": log.started_at.isoformat() if log.started_at else None,
        "finishedAt": log.finished_at.isoformat() if log.finished_at else None,
        "ok": log.ok,
        "itemsSeen": log.items_seen,
        "itemsNew": log.items_new,
        "itemsPromoted": log.items_promoted,
        "message": log.message,
    }


def _validation_log_dict(log: ValidationLog) -> dict:
    return {
        "id": log.id,
        "opportunityId": log.opportunity_id,
        "checkedAt": log.checked_at.isoformat() if log.checked_at else None,
        "statusCode": log.status_code,
        "result": log.result,
        "latencyMs": log.latency_ms,
        "message": log.message,
    }


# --------------------------- sources --------------------------- #
@router.get("/sources")
def list_sources(db: Session = Depends(get_db)):
    rows = db.scalars(select(Source).order_by(Source.id)).all()
    return [_source_dict(s) for s in rows]


@router.post("/sources", status_code=201)
def create_source(body: SourceIn, db: Session = Depends(get_db)):
    if body.type not in {t.value for t in SourceType}:
        raise HTTPException(422, f"Invalid source type {body.type!r}")
    source = Source(
        name=body.name,
        type=body.type,
        url=body.url,
        config=body.config or {},
        default_provider=body.default_provider,
        is_enabled=body.is_enabled,
    )
    db.add(source)
    db.commit()
    return _source_dict(source)


@router.patch("/sources/{source_id}")
def update_source(source_id: int, body: SourceUpdate, db: Session = Depends(get_db)):
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(404, "Source not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(source, field, value)
    db.commit()
    return _source_dict(source)


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(source_id: int, db: Session = Depends(get_db)):
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(404, "Source not found")
    # Detach/clean dependents first so the delete can't hit a foreign-key
    # error. Published opportunities are kept (just unlinked); this source's
    # staging rows, ingestion logs, and alerts are removed along with it.
    db.execute(update(Opportunity).where(Opportunity.source_id == source_id).values(source_id=None))
    db.execute(delete(RawOpportunity).where(RawOpportunity.source_id == source_id))
    db.execute(delete(IngestionLog).where(IngestionLog.source_id == source_id))
    db.execute(delete(Alert).where(Alert.source_id == source_id))
    db.delete(source)
    db.commit()


@router.post("/sources/{source_id}/probe")
def probe(source_id: int, db: Session = Depends(get_db)):
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(404, "Source not found")
    probe_source(source)
    db.commit()
    return _source_dict(source)


@router.post("/sources/{source_id}/ingest")
def ingest_one(source_id: int, db: Session = Depends(get_db)):
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(404, "Source not found")
    log = ingest_source(db, source)
    return _ingest_log_dict(log)


@router.post("/ingest")
def ingest_now(db: Session = Depends(get_db)):
    logs = ingest_all(db)
    return [_ingest_log_dict(log) for log in logs]


@router.post("/reseed")
def reseed(db: Session = Depends(get_db)):
    """Load/refresh the built-in seed: adds new listings (e.g. jobs) and
    recomputes freshness on existing rows. Idempotent."""
    return load_seed(db)


# --------------------------- approval queue --------------------------- #
@router.get("/queue")
def queue(db: Session = Depends(get_db)):
    rows = db.scalars(
        select(RawOpportunity)
        .where(RawOpportunity.status == RawStatus.pending.value)
        .order_by(RawOpportunity.created_at.desc())
        .limit(200)
    ).all()
    return [_raw_dict(r) for r in rows]


@router.post("/queue/{raw_id}/approve")
def approve(raw_id: int, db: Session = Depends(get_db)):
    raw = db.get(RawOpportunity, raw_id)
    if raw is None or raw.status != RawStatus.pending.value:
        raise HTTPException(404, "Pending item not found")
    opp = promote_raw_to_opportunity(db, raw)
    db.commit()
    return {"ok": True, "opportunityId": opp.id if opp else None}


@router.post("/queue/{raw_id}/reject")
def reject(raw_id: int, body: RejectIn, db: Session = Depends(get_db)):
    raw = db.get(RawOpportunity, raw_id)
    if raw is None or raw.status != RawStatus.pending.value:
        raise HTTPException(404, "Pending item not found")
    raw.status = RawStatus.rejected.value
    raw.reject_reason = body.reason
    db.commit()
    return {"ok": True}


# --------------------------- manual opportunities --------------------------- #
@router.post("/opportunities", status_code=201)
def submit_opportunity(body: ManualOpportunityIn, db: Session = Depends(get_db)):
    """Stage an admin-submitted opportunity; optionally promote immediately."""
    manual_source = db.scalars(
        select(Source).where(Source.type == SourceType.manual.value).order_by(Source.id)
    ).first()

    payload = {
        "cost": body.cost,
        "audit": body.audit,
        "certificate": body.certificate,
        "duration": body.duration,
        "tags": body.tags,
    }
    if body.kind:
        payload["kind"] = body.kind
    if body.expires_at:
        payload["expires_at"] = body.expires_at

    raw = RawOpportunity(
        source_id=manual_source.id if manual_source else None,
        external_id=None,
        title=body.title,
        url=body.url,
        description=body.description,
        provider=body.provider,
        suggested_category=body.category,
        raw_payload=payload,
        status=RawStatus.pending.value,
    )
    db.add(raw)
    db.flush()

    if body.approve:
        opp = promote_raw_to_opportunity(db, raw)
        db.commit()
        return {"ok": True, "queued": False, "opportunityId": opp.id if opp else None}
    db.commit()
    return {"ok": True, "queued": True, "rawId": raw.id}


@router.delete("/opportunities/{opp_id}", status_code=204)
def deactivate_opportunity(opp_id: int, db: Session = Depends(get_db)):
    opp = db.get(Opportunity, opp_id)
    if opp is None:
        raise HTTPException(404, "Opportunity not found")
    opp.is_active = False
    db.commit()


# --------------------------- logs / stale / validate / alerts --------------- #
@router.get("/logs/ingestion")
def ingestion_logs(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.scalars(
        select(IngestionLog).order_by(IngestionLog.started_at.desc()).limit(min(limit, 200))
    ).all()
    return [_ingest_log_dict(log) for log in rows]


@router.get("/logs/validation")
def validation_logs(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.scalars(
        select(ValidationLog).order_by(ValidationLog.checked_at.desc()).limit(min(limit, 200))
    ).all()
    return [_validation_log_dict(log) for log in rows]


@router.get("/stale")
def stale(days: int = 7, db: Session = Depends(get_db)):
    cutoff = utcnow() - timedelta(days=days)
    rows = db.scalars(
        select(Opportunity)
        .where(
            Opportunity.is_active.is_(True),
            (Opportunity.last_verified_at.is_(None)) | (Opportunity.last_verified_at < cutoff),
        )
        .order_by(Opportunity.last_verified_at.asc())
        .limit(200)
    ).all()
    return [
        {
            "id": o.id,
            "title": o.title,
            "provider": o.provider,
            "lastVerifiedAt": o.last_verified_at.isoformat() if o.last_verified_at else None,
            "freshnessScore": o.freshness_score,
        }
        for o in rows
    ]


@router.post("/validate")
def run_validation(db: Session = Depends(get_db)):
    from ..daemon.validation import validate_cycle

    return validate_cycle(db)


@router.get("/alerts")
def alerts(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.scalars(select(Alert).order_by(Alert.created_at.desc()).limit(min(limit, 200))).all()
    return [
        {
            "id": a.id,
            "type": a.type,
            "message": a.message,
            "opportunityId": a.opportunity_id,
            "sourceId": a.source_id,
            "payload": a.payload,
            "isRead": a.is_read,
            "createdAt": a.created_at.isoformat() if a.created_at else None,
        }
        for a in rows
    ]


@router.post("/alerts/{alert_id}/read")
def mark_alert_read(alert_id: int, db: Session = Depends(get_db)):
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(404, "Alert not found")
    alert.is_read = True
    db.commit()
    return {"ok": True}


# --------------------------- career agent --------------------------------- #
@router.post("/career/analyze")
def career_analyze(body: CareerAnalyzeIn, db: Session = Depends(get_db)):
    """Run the Career Agent on pasted CV text. The CV is processed transiently
    and never stored — only the derived report is persisted."""
    if not (body.cv_text or "").strip():
        raise HTTPException(422, "cv_text is required")
    return career_service.analyze(
        db, cv_text=body.cv_text, goal=body.goal, category=body.category
    )


@router.post("/career/analyze-file")
async def career_analyze_file(
    file: UploadFile = File(...),
    goal: str | None = Form(None),
    category: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Upload a CV (PDF / DOCX / TXT); text is extracted, then analyzed. The
    file is read into memory, never written to disk or stored."""
    data = await file.read()
    if not data:
        raise HTTPException(422, "Empty file")
    if len(data) > cv_extract.MAX_BYTES:
        raise HTTPException(413, "File too large (max 8 MB)")
    text = cv_extract.extract_text(file.filename or "", data)
    if len((text or "").strip()) < 20:
        raise HTTPException(
            422,
            "Could not extract text from this file. If it's a scanned PDF, paste the text instead.",
        )
    return career_service.analyze(db, cv_text=text, goal=goal, category=category)


@router.get("/career/reports")
def career_reports(limit: int = 20, db: Session = Depends(get_db)):
    rows = db.scalars(
        select(CareerReport).order_by(CareerReport.created_at.desc()).limit(min(limit, 100))
    ).all()
    return [
        {
            "id": r.id,
            "goal": r.goal,
            "haveSkills": r.have_skills,
            "gapSkills": r.gap_skills,
            "matchedIds": r.matched_ids,
            "llmUsed": r.llm_used,
            "createdAt": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
