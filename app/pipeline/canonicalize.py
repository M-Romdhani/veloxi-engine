"""Deterministic URL canonicalization for dedupe."""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query params that never identify a resource (tracking / analytics).
_DROP_PARAMS = {
    "gclid",
    "fbclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_",
    "referrer",
    "source",
    "src",
}
_DROP_PREFIXES = ("utm_",)


def _keep_param(key: str) -> bool:
    k = key.lower()
    if k in _DROP_PARAMS:
        return False
    return not any(k.startswith(p) for p in _DROP_PREFIXES)


def canonical_url(raw: str) -> str:
    """Normalize a URL so equivalent links collapse to one string.

    Rules: force https, lowercase scheme+host, strip leading www./m.,
    drop default ports, remove fragment, drop tracking params, sort the
    rest, collapse duplicate slashes, strip trailing slash (except root).
    Idempotent: ``canonical_url(canonical_url(x)) == canonical_url(x)``.
    """
    if not raw:
        return ""
    raw = raw.strip()
    if "://" not in raw:
        raw = "https://" + raw

    parts = urlsplit(raw)
    scheme = "https"

    host = (parts.hostname or "").lower()
    for prefix in ("www.", "m."):
        if host.startswith(prefix):
            host = host[len(prefix):]
            break

    netloc = host
    if parts.port and parts.port not in (80, 443):
        netloc = f"{host}:{parts.port}"
    if parts.username:  # preserve credentials if (rarely) present
        creds = parts.username + (f":{parts.password}" if parts.password else "")
        netloc = f"{creds}@{netloc}"

    # Path: collapse duplicate slashes, strip trailing slash (keep root).
    path = parts.path or "/"
    while "//" in path:
        path = path.replace("//", "/")
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if _keep_param(k)]
    kept.sort()
    query = urlencode(kept)

    return urlunsplit((scheme, netloc, path, query, ""))
