from __future__ import annotations

import asyncio
from importlib import resources

import uvicorn
from alembic import command
from alembic.config import Config as AlembicConfig

from vidi_pr.config.operator import OperatorConfig
from vidi_pr.llm.client import OpenAICompatClient
from vidi_pr.orchestration.handlers import DEFAULT_BOT_LOGIN, OrchestrationHandler
from vidi_pr.pipeline.reviewer import Reviewer
from vidi_pr.pipeline.worker import Worker
from vidi_pr.storage.db import Database, make_database_url
from vidi_pr.transport.github_client import GitHubClient
from vidi_pr.transport.logging_setup import setup_logging
from vidi_pr.transport.server import create_app


def _run_migrations(db_url: str) -> None:
    script_location = resources.files("vidi_pr.storage") / "alembic"
    config = AlembicConfig()
    config.set_main_option("script_location", str(script_location))
    config.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(config, "head")


async def _serve() -> None:
    operator_config = OperatorConfig.load()
    setup_logging(operator_config.logging)
    _run_migrations(make_database_url(operator_config.storage.db_path))

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
    )

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
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
