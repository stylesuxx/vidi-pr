from __future__ import annotations

from typing import Any

import structlog

from vidi_pr.config.operator import DefaultsConfig
from vidi_pr.config.repo import RepoConfigLoader
from vidi_pr.models.storage import TriggerKind
from vidi_pr.orchestration.authz import is_authorized
from vidi_pr.orchestration.locks import try_enqueue_review
from vidi_pr.orchestration.triggers import parse_trigger
from vidi_pr.storage.db import Database
from vidi_pr.transport.github_client import GitHubClient

DEFAULT_BOT_LOGIN = "vidi-pr[bot]"

_AUTO_TRIGGER_ACTIONS = frozenset({"opened", "ready_for_review"})

_logger = structlog.get_logger(__name__)


class OrchestrationHandler:
    def __init__(
        self,
        *,
        client: GitHubClient,
        database: Database,
        defaults: DefaultsConfig,
        bot_login: str = DEFAULT_BOT_LOGIN,
    ) -> None:
        self._client = client
        self._database = database
        self._defaults = defaults
        self._bot_login = bot_login

    async def on_pull_request(self, event: Any) -> None:
        action = getattr(event, "action", None)
        if action not in _AUTO_TRIGGER_ACTIONS:
            return

        pr = event.pull_request
        if getattr(pr, "draft", False):
            return

        repo = event.repository.full_name
        installation_id = event.installation.id

        async with self._database.sessionmaker() as session:
            job = await try_enqueue_review(
                session,
                installation_id=installation_id,
                repo=repo,
                pr_number=pr.number,
                head_sha=pr.head.sha,
                trigger_kind=TriggerKind.AUTO,
            )

        if job is None:
            _logger.info("auto-trigger dropped: lock held", repo=repo, pr_number=pr.number)
        else:
            _logger.info("auto-trigger enqueued", repo=repo, pr_number=pr.number, job_id=job.id)

    async def on_issue_comment(self, event: Any) -> None:
        if getattr(event, "action", None) != "created":
            return

        if getattr(event.issue, "pull_request", None) is None:
            return

        sender_login = event.sender.login
        if sender_login == self._bot_login:
            return

        body = getattr(event.comment, "body", None)
        parsed = parse_trigger(body)
        if parsed is None:
            return

        repo = event.repository.full_name
        installation_id = event.installation.id
        comment_id = event.comment.id
        pr_number = event.issue.number

        pr = await self._client.get_pr(installation_id, repo, pr_number)

        loader = RepoConfigLoader(
            self._client.for_installation(installation_id),
            defaults=self._defaults,
        )
        repo_config = await loader.load(
            repo,
            base_ref=pr.base_ref,
            default_branch=event.repository.default_branch,
        )

        if not repo_config.enabled:
            _logger.info("comment-trigger ignored: reviews disabled", repo=repo)
            return

        author_association = getattr(event.comment, "author_association", "") or ""
        if not is_authorized(
            login=sender_login,
            author_association=author_association,
            repo_config=repo_config,
        ):
            await self._client.react_to_comment(installation_id, repo, comment_id, "-1")
            _logger.info(
                "comment-trigger rejected: unauthorized",
                repo=repo,
                login=sender_login,
            )
            return

        await self._client.react_to_comment(installation_id, repo, comment_id, "eyes")

        async with self._database.sessionmaker() as session:
            job = await try_enqueue_review(
                session,
                installation_id=installation_id,
                repo=repo,
                pr_number=pr_number,
                head_sha=pr.head_sha,
                trigger_kind=TriggerKind.COMMENT,
                extra_context=parsed.extra_context,
            )

        if job is None:
            _logger.info("comment-trigger dropped: lock held", repo=repo, pr_number=pr_number)
        else:
            _logger.info(
                "comment-trigger enqueued",
                repo=repo,
                pr_number=pr_number,
                job_id=job.id,
                extra_context_present=parsed.extra_context is not None,
            )
