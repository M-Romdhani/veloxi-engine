"""Extract plain text from an uploaded CV (PDF / DOCX / plain text).

Dependency-light and resilient: the PDF library is imported lazily and guarded
so a missing/broken native dependency never breaks app import or the non-PDF
paths. When a local PDF parse yields nothing (e.g. a scanned/image PDF) and an
LLM is configured, we fall back to Claude's native PDF reading.
"""
from __future__ import annotations

import io
import logging

logger = logging.getLogger("veloxi.cv")

MAX_BYTES = 8 * 1024 * 1024  # 8 MB upload ceiling


def extract_text(filename: str, data: bytes) -> str:
    """Best-effort plain text from an uploaded file. Returns "" if nothing usable."""
    name = (filename or "").lower()
    if name.endswith(".pdf") or data[:5].startswith(b"%PDF"):
        return _from_pdf(data)
    if name.endswith(".docx"):
        return _from_docx(data)
    return _from_text(data)


def _from_text(data: bytes) -> str:
    for enc in ("utf-8", "latin-1"):
        try:
            return data.decode(enc).strip()
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore").strip()


def _from_pdf(data: bytes) -> str:
    # pypdf eagerly imports `cryptography`; on a misconfigured host that import
    # can raise a pyo3 PanicException (a BaseException), so guard broadly and
    # degrade to the LLM fallback / empty rather than crashing the request.
    text = ""
    try:
        from pypdf import PdfReader  # imported lazily on purpose

        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except BaseException as exc:  # noqa: BLE001 - includes pyo3 PanicException
        logger.warning("pypdf extraction failed: %s", exc)

    if len(text) >= 40:
        return text

    # Scanned/image PDF or no working extractor: try Claude's native PDF reading.
    from ..pipeline.llm import transcribe_pdf_with_llm

    return (transcribe_pdf_with_llm(data) or text).strip()


def _from_docx(data: bytes) -> str:
    try:
        import docx  # python-docx

        doc = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs).strip()
    except Exception as exc:  # noqa: BLE001 - best-effort
        logger.warning("docx extraction failed: %s", exc)
        return ""
