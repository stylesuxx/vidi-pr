from __future__ import annotations

import asyncio
from importlib import resources

import structlog
import uvicorn
from alembic import command
from alembic.config import Config as AlembicConfig

from vidi_pr.config.operator import OperatorConfig
from vidi_pr.llm.client import OpenAICompatClient
from vidi_pr.llm.errors import LLMError
from vidi_pr.orchestration.handlers import DEFAULT_BOT_LOGIN, OrchestrationHandler
from vidi_pr.pipeline.reviewer import Reviewer
from vidi_pr.pipeline.worker import Worker
from vidi_pr.storage.db import Database, make_database_url
from vidi_pr.transport.github_client import GitHubClient
from vidi_pr.transport.logging_setup import setup_logging
from vidi_pr.transport.server import create_app

_logger = structlog.get_logger(__name__)


def _run_migrations(db_url: str) -> None:
    script_location = resources.files("vidi_pr.storage") / "alembic"
    config = AlembicConfig()
    config.set_main_option("script_location", str(script_location))
    config.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(config, "head")


async def _probe_llm(client: OpenAICompatClient, *, expected_model: str) -> None:
    try:
        available = await client.list_models()
    except LLMError as exc:
        _logger.warning(
            "LLM endpoint not reachable at startup; reviews will fail until it is up",
            error=str(exc),
        )
        return

    if expected_model in available:
        _logger.info("LLM endpoint ready", model=expected_model, available=len(available))
        return

    _logger.warning(
        "configured model not present on LLM endpoint; reviews will fail until it is loaded",
        expected_model=expected_model,
        available_models=available,
    )


async def _serve(operator_config: OperatorConfig) -> None:
    database = await Database.open(operator_config.storage.db_path)
    private_key = operator_config.github.private_key_path.read_text(encoding="utf-8")
    github_client = GitHubClient(
        app_id=operator_config.github.app_id,
        private_key=private_key,
    )
    llm_client = OpenAICompatClient(
        base_url=operator_config.llm.base_url,
        model=operator_config.llm.model,
        api_key=(
            operator_config.llm_api_key.get_secret_value()
            if operator_config.llm_api_key is not None
            else None
        ),
        timeout=float(operator_config.llm.timeout_seconds),
        extra_body=operator_config.llm.extra_body,
    )

    await _probe_llm(llm_client, expected_model=operator_config.llm.model)

    try:
        handler = OrchestrationHandler(
            client=github_client,
            database=database,
            defaults=operator_config.defaults,
        )

        reviewer = Reviewer(
            github_client=github_client,
            llm_client=llm_client,
            defaults=operator_config.defaults,
            pipeline_config=operator_config.pipeline,
            llm_config=operator_config.llm,
            bot_login=DEFAULT_BOT_LOGIN,
        )

        worker = Worker(
            database=database,
            github_client=github_client,
            reviewer=reviewer,
            operator_config=operator_config,
        )
        worker_task = asyncio.create_task(worker.run_forever())

        app = create_app(
            config=operator_config,
            database=database,
            handler=handler,
        )

        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=operator_config.server.host,
                port=operator_config.server.port,
                forwarded_allow_ips=[
                    str(network) for network in operator_config.server.forwarded_allow_ips
                ]
                or None,
                log_config=None,
            )
        )

        try:
            await server.serve()
        finally:
            worker.stop()
            await worker_task

    finally:
        await llm_client.aclose()
        await github_client.aclose()
        await database.aclose()


def main() -> None:
    operator_config = OperatorConfig.load()
    setup_logging(operator_config.logging)
    # Run Alembic synchronously before entering the asyncio loop; the env.py
    # uses `asyncio.run()` internally, which would nest if called from inside
    # an active loop.
    _run_migrations(make_database_url(operator_config.storage.db_path))
    asyncio.run(_serve(operator_config))


if __name__ == "__main__":
    main()
