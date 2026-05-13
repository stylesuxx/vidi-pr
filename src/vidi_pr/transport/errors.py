from vidi_pr.errors import VidiPrError


class GitHubError(VidiPrError):
    pass


class GitHubAuthError(GitHubError):
    pass


class GitHubNotFound(GitHubError):
    pass


class GitHubTransientError(GitHubError):
    pass


class GitHubPermanentError(GitHubError):
    pass


class WebhookError(VidiPrError):
    pass


class WebhookAuthError(WebhookError):
    pass


class WebhookBadRequest(WebhookError):
    pass
