from vidi_pr.config.repo import RepoConfig
from vidi_pr.orchestration.authz import is_authorized


def _config(*, users: list[str] | None = None, associations: list[str] | None = None) -> RepoConfig:
    return RepoConfig(
        allowed_users=users or [],
        allowed_associations=associations or [],
    )


def test_login_in_allowed_users_is_authorized() -> None:
    config = _config(users=["stylesuxx"])
    assert is_authorized(login="stylesuxx", author_association="NONE", repo_config=config) is True


def test_association_in_allowed_associations_is_authorized() -> None:
    config = _config(associations=["OWNER", "COLLABORATOR"])
    assert is_authorized(login="alice", author_association="OWNER", repo_config=config) is True


def test_association_matching_is_case_insensitive() -> None:
    config = _config(associations=["OWNER"])
    assert is_authorized(login="alice", author_association="owner", repo_config=config) is True


def test_unauthorized_when_neither_match() -> None:
    config = _config(users=["stylesuxx"], associations=["OWNER"])
    assert is_authorized(login="randomuser", author_association="NONE", repo_config=config) is False


def test_empty_config_rejects_everyone() -> None:
    config = _config()
    assert is_authorized(login="stylesuxx", author_association="OWNER", repo_config=config) is False
