from __future__ import annotations

from typing import Any, Protocol

import structlog
from githubkit.webhooks import parse as parse_webhook
from githubkit.webhooks import verify as verify_signature
from sqlalchemy.ext.asyncio import AsyncSession

from vidi_pr.storage.dedup import record_delivery
from vidi_pr.transport.errors import WebhookAuthError, WebhookBadRequest

# GitHub caps every webhook delivery at 25 MB
# (https://docs.github.com/en/webhooks/webhook-events-and-payloads).
# Anything larger is either misconfigured or hostile; reject before HMAC.
MAX_BODY_BYTES = 25 * 1024 * 1024

_logger = structlog.get_logger(__name__)


class EventHandler(Protocol):
    async def on_pull_request(self, event: Any) -> None: ...

    async def on_issue_comment(self, event: Any) -> None: ...


class LoggingEventHandler:
    async def on_pull_request(self, event: Any) -> None:
        action = getattr(event, "action", "?")
        pr = getattr(event, "pull_request", None)
        pr_number = getattr(pr, "number", "?") if pr is not None else "?"

        _logger.info("pull_request received", action=action, pr_number=pr_number)

    async def on_issue_comment(self, event: Any) -> None:
        action = getattr(event, "action", "?")
        comment = getattr(event, "comment", None)
        comment_id = getattr(comment, "id", "?") if comment is not None else "?"

        _logger.info("issue_comment received", action=action, comment_id=comment_id)


async def process_webhook(
    *,
    body: bytes,
    event_type: str | None,
    delivery_id: str | None,
    signature: str | None,
    secret: str,
    session: AsyncSession,
    handler: EventHandler,
) -> bool:
    """
    Verify, dedup, parse, and dispatch a single webhook delivery.

    Returns True if the delivery was newly recorded and dispatched, False if
    it was a duplicate (already-seen `X-GitHub-Delivery`). Raises
    `WebhookAuthError` for missing/invalid signatures, `WebhookBadRequest`
    for missing required headers or unparseable payloads.
    """
    if signature is None:
        raise WebhookAuthError("X-Hub-Signature-256 missing")

    if event_type is None:
        raise WebhookBadRequest("X-GitHub-Event missing")

    if delivery_id is None:
        raise WebhookBadRequest("X-GitHub-Delivery missing")

    if not verify_signature(secret, body, signature):
        raise WebhookAuthError("invalid signature")

    is_new = await record_delivery(session, delivery_id)
    await session.commit()

    if not is_new:
        _logger.info("duplicate delivery dropped", delivery_id=delivery_id)
        return False

    try:
        event = parse_webhook(event_type, body)
    except Exception as exc:
        raise WebhookBadRequest(f"could not parse {event_type}: {exc}") from exc

    await _dispatch(event_type, event, handler)
    return True


async def _dispatch(event_type: str, event: Any, handler: EventHandler) -> None:
    if event_type == "pull_request":
        await handler.on_pull_request(event)
    elif event_type == "issue_comment":
        await handler.on_issue_comment(event)
    else:
        _logger.info("ignoring unsupported event", event_type=event_type)
