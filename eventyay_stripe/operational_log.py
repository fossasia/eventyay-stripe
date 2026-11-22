"""Privacy-safe operational logs for this plugin.

Delegates to the host logger when it is importable. Otherwise uses
``eventyay.plugins``. Logging never raises into product code.

Emails, names, tokens, secrets, and request or response bodies are dropped.
Only opaque IDs, status codes, durations, and safe error codes are kept.
"""

from __future__ import annotations

import functools
import logging
import re
from contextvars import ContextVar

try:
    from celery import current_task as _CELERY_CURRENT_TASK
except Exception:
    _CELERY_CURRENT_TASK = None

try:
    from eventyay.base.operational_logging import (
        get_job_id as _HOST_GET_JOB_ID,
    )
    from eventyay.base.operational_logging import (
        get_request_id as _HOST_GET_REQUEST_ID,
    )
    from eventyay.base.operational_logging import (
        log_event as _HOST_LOG_EVENT,
    )
except Exception:
    _HOST_LOG_EVENT = None
    _HOST_GET_REQUEST_ID = None
    _HOST_GET_JOB_ID = None

OUTCOME_SUCCESS = "success"
OUTCOME_FAILURE = "failure"

_ACTIVE_REQUEST_ID: ContextVar[str | None] = ContextVar("eventyay_stripe_request_id", default=None)
_ACTIVE_JOB_ID: ContextVar[str | None] = ContextVar("eventyay_stripe_job_id", default=None)

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_LOGGER = logging.getLogger("eventyay.plugins")
_INT_FIELDS = frozenset(
    {
        "event_id",
        "order_id",
        "user_id",
        "status",
        "duration_ms",
        "retry_count",
    }
)
_IDENTIFIER_FIELDS = frozenset(
    {
        "error_code",
        "backend",
        "job_name",
        "job_id",
        "request_id",
        "payment_provider",
        "model",
    }
)


def _safe_identifier(value):
    if isinstance(value, str) and _SAFE_IDENTIFIER.fullmatch(value):
        return value
    return None


def bind_request_id(request_id):
    return _ACTIVE_REQUEST_ID.set(_safe_identifier(request_id))


def reset_request_id(token=None):
    if token is not None:
        _ACTIVE_REQUEST_ID.reset(token)
    else:
        _ACTIVE_REQUEST_ID.set(None)


def get_request_id():
    rid = _ACTIVE_REQUEST_ID.get()
    if rid is None and _HOST_GET_REQUEST_ID is not None:
        try:
            rid = _HOST_GET_REQUEST_ID()
        except Exception:
            rid = None
    return _safe_identifier(rid)


def get_job_id():
    jid = _ACTIVE_JOB_ID.get()
    if jid is None and _HOST_GET_JOB_ID is not None:
        try:
            jid = _HOST_GET_JOB_ID()
        except Exception:
            jid = None
    if jid is None and _CELERY_CURRENT_TASK is not None:
        req = getattr(_CELERY_CURRENT_TASK, "request", None)
        jid = getattr(req, "id", None) if req is not None else None
    return _safe_identifier(jid)


def stripe_error_code(exc, default="stripe_error"):
    """Return an allowlisted error code for a Stripe exception."""
    code = getattr(exc, "code", None)
    if not code:
        json_body = getattr(exc, "json_body", None)
        if isinstance(json_body, dict):
            err = json_body.get("error")
            if isinstance(err, dict):
                code = err.get("code")
    if isinstance(code, str) and _safe_identifier(code) is not None:
        return code
    return default


def _clean(fields):
    extra = {}
    for key, value in fields.items():
        if value is None or value == "":
            continue
        if key in _INT_FIELDS:
            if isinstance(value, bool) or not isinstance(value, int):
                continue
            extra[key] = value
            continue
        if key in _IDENTIFIER_FIELDS:
            cleaned = _safe_identifier(value if isinstance(value, str) else None)
            if cleaned is not None:
                extra[key] = cleaned
            continue
        if key == "object_id":
            if isinstance(value, bool):
                continue
            if isinstance(value, int):
                extra[key] = value
            else:
                cleaned = _safe_identifier(str(value))
                if cleaned is not None:
                    extra[key] = cleaned
    return extra


def log_operation(action, outcome, **fields):
    """Emit one allowlisted operational line. Failures are swallowed."""
    try:
        if not isinstance(action, str) or _safe_identifier(action) is None:
            return
        if outcome not in (OUTCOME_SUCCESS, OUTCOME_FAILURE):
            outcome = OUTCOME_FAILURE
        level = logging.WARNING if outcome == OUTCOME_FAILURE else logging.INFO
        payload = _clean(fields)
        if "job_id" not in payload:
            active_job_id = get_job_id()
            if active_job_id is not None:
                payload["job_id"] = active_job_id
        if "request_id" not in payload:
            active_request_id = get_request_id()
            if active_request_id is not None:
                payload["request_id"] = active_request_id
        if _HOST_LOG_EVENT is not None:
            try:
                _HOST_LOG_EVENT("plugins", action, outcome, level=level, **payload)
                return
            except Exception:
                pass
        extra = {
            "component": "plugins",
            "outcome": outcome,
            "action": action,
            **payload,
        }
        _LOGGER.log(level, action, extra=extra)
    except Exception:
        return


def log_plugin_loaded(backend):
    log_operation("plugin.loaded", OUTCOME_SUCCESS, backend=backend)


def _extract_task_and_job_id(args):
    task = args[0] if args and hasattr(args[0], "request") else _CELERY_CURRENT_TASK
    req = getattr(task, "request", None) if task is not None else None
    job_id = getattr(req, "id", None) if req is not None else None
    return task, job_id


def _will_autoretry(task, exc):
    if task is None or not hasattr(task, "request"):
        return False
    autoretry_for = getattr(task, "autoretry_for", None)
    if not autoretry_for:
        return False
    if isinstance(autoretry_for, (list, set, tuple)):
        autoretry_for = tuple(autoretry_for)
    if not isinstance(exc, autoretry_for):
        return False
    dont_autoretry_for = getattr(task, "dont_autoretry_for", None)
    if dont_autoretry_for:
        if isinstance(dont_autoretry_for, (list, set, tuple)):
            dont_autoretry_for = tuple(dont_autoretry_for)
        if isinstance(exc, dont_autoretry_for):
            return False
    current = getattr(task.request, "retries", 0)
    if not isinstance(current, int) or isinstance(current, bool):
        return False
    limit = getattr(task, "max_retries", 3)
    if limit is None:
        return True
    if isinstance(limit, int) and not isinstance(limit, bool):
        return current < limit
    return False


def traced_job(job_name):
    """Log job boundaries without changing the return value or exception."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            task, job_id = _extract_task_and_job_id(args)
            if job_id is None:
                job_id = get_job_id()
            token = _ACTIVE_JOB_ID.set(_safe_identifier(job_id))
            try:
                log_operation("job.start", OUTCOME_SUCCESS, job_name=job_name, job_id=job_id)
                try:
                    result = fn(*args, **kwargs)
                except Exception as exc:
                    retried = type(exc).__name__ == "Retry" or _will_autoretry(task, exc)
                    req = getattr(task, "request", None) if task is not None else None
                    retries = getattr(req, "retries", None) if req is not None else None
                    log_operation(
                        "job.retry" if retried else "job.fail",
                        OUTCOME_FAILURE,
                        job_name=job_name,
                        job_id=job_id,
                        error_code="retry" if retried else type(exc).__name__,
                        retry_count=retries if isinstance(retries, int) and not isinstance(retries, bool) else None,
                    )
                    raise
                log_operation("job.finish", OUTCOME_SUCCESS, job_name=job_name, job_id=job_id)
                return result
            finally:
                _ACTIVE_JOB_ID.reset(token)

        return wrapper

    return decorator
