from __future__ import annotations

import asyncio
from importlib import resources

import uvicorn
from alembic import command
from alembic.config import Config as AlembicConfig

from vidi_pr.config.operator import OperatorConfig
from vidi_pr.orchestration.handlers import OrchestrationHandler
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
    try:
        handler = OrchestrationHandler(
            client=github_client,
            database=database,
            defaults=operator_config.defaults,
        )
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
        await server.serve()
    finally:
        await github_client.aclose()
        await database.aclose()


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
