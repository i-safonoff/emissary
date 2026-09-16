"""A real client against the GitHub REST API, built on emissary -- proof
the framework holds up against an API this project didn't design.

    from examples.github_client import GitHubClient

    async with GitHubClient(token="ghp_...") as gh:
        repo = await gh.get_repo("i-safonoff", "unicall")
        async for issue in gh.list_issues("i-safonoff", "unicall"):
            print(issue.number, issue.title)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel

from emissary import (
    ApiClient,
    BearerTokenAuth,
    JsonFieldErrorMapper,
    LinkHeaderPagination,
    endpoint,
)


class Owner(BaseModel):
    login: str
    id: int


class Repo(BaseModel):
    id: int
    name: str
    full_name: str
    private: bool
    html_url: str
    description: str | None = None
    stargazers_count: int = 0
    # Extra fields (and GitHub's repo payload has dozens) are dropped, not
    # rejected -- pydantic's own default. A partial model like this one
    # only works at all because of it.


class Issue(BaseModel):
    id: int
    number: int
    title: str
    state: str
    html_url: str
    user: Owner


class NewIssue(BaseModel):
    title: str
    body: str | None = None


class GitHubClient(ApiClient):
    base_url = "https://api.github.com"
    error_mapper = JsonFieldErrorMapper("message")

    def __init__(self, token: str, **kwargs: Any) -> None:
        super().__init__(auth=BearerTokenAuth(token), **kwargs)

    @endpoint("GET", "/repos/{owner}/{repo}")
    async def get_repo(self, owner: str, repo: str) -> Repo:
        # The body never runs: @endpoint replaces this function entirely.
        # It's here (rather than `...`) because mypy --strict flags a bare
        # `...` body as a possibly-forgotten implementation; this says so.
        raise NotImplementedError

    @endpoint("GET", "/repos/{owner}/{repo}/issues", paginate=LinkHeaderPagination())
    def list_issues(self, owner: str, repo: str) -> AsyncIterator[Issue]:
        raise NotImplementedError

    @endpoint("POST", "/repos/{owner}/{repo}/issues", idempotent=False)
    async def create_issue(self, owner: str, repo: str, body: NewIssue) -> Issue:
        raise NotImplementedError
