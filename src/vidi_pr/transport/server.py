from __future__ import annotations

from fastapi import FastAPI, Request, Response

from vidi_pr.config.operator import OperatorConfig
from vidi_pr.storage.db import Database
from vidi_pr.transport.errors import WebhookAuthError, WebhookBadRequest
from vidi_pr.transport.webhook import MAX_BODY_BYTES, EventHandler, process_webhook


def create_app(
    *,
    config: OperatorConfig,
    database: Database,
    handler: EventHandler,
) -> FastAPI:
    app = FastAPI()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/webhook")
    async def webhook(request: Request) -> Response:
        content_length_header = request.headers.get("content-length")
        if content_length_header is not None:
            try:
                declared = int(content_length_header)
            except ValueError:
                return Response(status_code=400)

            if declared > MAX_BODY_BYTES:
                return Response(status_code=413)

        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            return Response(status_code=413)

        try:
            async with database.sessionmaker() as session:
                is_new = await process_webhook(
                    body=body,
                    event_type=request.headers.get("X-GitHub-Event"),
                    delivery_id=request.headers.get("X-GitHub-Delivery"),
                    signature=request.headers.get("X-Hub-Signature-256"),
                    secret=config.webhook_secret.get_secret_value(),
                    session=session,
                    handler=handler,
                )

        except WebhookAuthError:
            return Response(status_code=401)

        except WebhookBadRequest:
            return Response(status_code=400)

        return Response(status_code=200 if is_new else 202)

    return app
