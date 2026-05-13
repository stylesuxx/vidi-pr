from __future__ import annotations

from vidi_pr.config.repo import RepoConfig


def is_authorized(*, login: str, author_association: str, repo_config: RepoConfig) -> bool:
    if login in repo_config.allowed_users:
        return True

    allowed = {entry.upper() for entry in repo_config.allowed_associations}
    return author_association.upper() in allowed
