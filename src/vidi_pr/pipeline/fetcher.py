from __future__ import annotations

import re

from vidi_pr.models.review import PRContent
from vidi_pr.transport.github_client import GitHubClient

# Same pattern the orchestration trigger parser uses; we cannot import it
# without coupling layers, so the regex lives here too. Comments that match
# this are review-trigger commands; we drop them from the conversation so
# the model does not see them as part of the review history.
_TRIGGER_PATTERN = re.compile(r"^@vidi-pr\s+review\b", re.IGNORECASE | re.MULTILINE)


async def fetch_pr_content(
    client: GitHubClient,
    *,
    installation_id: int,
    repo: str,
    pr_number: int,
    include_conversation: bool,
    bot_login: str,
) -> PRContent:
    """
    Pull the current PR metadata, changed files, and (optionally) the issue
    comment conversation. The bot's own comments and any comment matching the
    review-trigger pattern are filtered out of the conversation so they never
    feed back into the prompt.
    """
    pr = await client.get_pr(installation_id, repo, pr_number)
    files = await client.get_pr_files(installation_id, repo, pr_number)

    if not include_conversation:
        return PRContent(pr=pr, files=files, conversation=[])

    all_comments = await client.get_pr_comments(installation_id, repo, pr_number)
    conversation = [
        comment
        for comment in all_comments
        if comment.author_login != bot_login and not _TRIGGER_PATTERN.search(comment.body)
    ]
    return PRContent(pr=pr, files=files, conversation=conversation)
