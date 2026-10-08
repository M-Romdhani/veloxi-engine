"""Shared FastAPI dependencies."""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from .config import settings


def require_admin(x_admin_token: str = Header(default="")) -> bool:
    """Constant-time check of the admin token header.

    With no ADMIN_TOKEN configured the admin API is locked rather than open, so
    a deployment that forgot to set one never accepts a guessable default.
    """
    if not settings.admin_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API disabled: set ADMIN_TOKEN to enable it",
        )
    if not hmac.compare_digest(x_admin_token or "", settings.admin_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Admin-Token",
        )
    return True
