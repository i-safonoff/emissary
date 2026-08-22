from __future__ import annotations

import json

import pytest
from examples.github_client import GitHubClient, Issue, NewIssue, Repo
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request, Response

from emissary import NotFoundError

# Real shape, from `gh api repos/i-safonoff/unicall` -- trimmed, but every
# field kept is exactly as GitHub sent it, plus extras (node_id, fork,
# forks_url, ...) that Repo doesn't model at all. That's the point: a real
# response has dozens of fields this project will never need, and pydantic
# drops what it isn't told to keep rather than rejecting the response for
# knowing more than the model does.
REAL_REPO_RESPONSE = {
    "id": 1371806252,
    "node_id": "R_kgDOUcQaLA",
    "name": "unicall",
    "full_name": "i-safonoff/unicall",
    "private": False,
    "owner": {
        "login": "i-safonoff",
        "id": 282231943,
        "type": "User",
        "site_admin": False,
    },
    "html_url": "https://github.com/i-safonoff/unicall",
    "description": "Collapse concurrent async calls to the same thing into one flight",
    "fork": False,
    "url": "https://api.github.com/repos/i-safonoff/unicall",
    "forks_url": "https://api.github.com/repos/i-safonoff/unicall/forks",
    "stargazers_count": 1,
    "language": "Python",
    "default_branch": "main",
}

# Real shape, from a public issue on microsoft/vscode -- same trimming and
# same intent: user alone carries a dozen fields Owner doesn't model.
REAL_ISSUE_RESPONSE = {
    "id": 5467913329,
    "node_id": "PR_kwDOAiTA-c6cAbCd",
    "number": 336340,
    "title": "sessions: keep Codicon confetti behind conversations",
    "state": "open",
    "html_url": "https://github.com/microsoft/vscode/pull/336340",
    "user": {
        "login": "TylerLeonhardt",
        "id": 2644648,
        "type": "User",
        "site_admin": True,
    },
    "created_at": "2026-09-15T22:12:53Z",
    "body": "## Summary\n\n- Keep every painted Codicon inside the background stacking context",
}

# Real shape, from `gh api repos/i-safonoff/this-does-not-exist-xyz`.
REAL_404_RESPONSE = {
    "message": "Not Found",
    "documentation_url": "https://docs.github.com/rest/repos/repos#get-a-repository",
    "status": "404",
}


def _client_for(httpserver: HTTPServer) -> type[GitHubClient]:
    class TestClient(GitHubClient):
        base_url = httpserver.url_for("")

    return TestClient


async def test_get_repo_parses_a_real_github_response(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/repos/i-safonoff/unicall").respond_with_json(REAL_REPO_RESPONSE)

    async with _client_for(httpserver)(token="test-token") as client:
        repo = await client.get_repo("i-safonoff", "unicall")

    assert repo == Repo(
        id=1371806252,
        name="unicall",
        full_name="i-safonoff/unicall",
        private=False,
        html_url="https://github.com/i-safonoff/unicall",
        description="Collapse concurrent async calls to the same thing into one flight",
        stargazers_count=1,
    )


async def test_a_404_carries_githubs_own_message(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/repos/i-safonoff/missing").respond_with_json(
        REAL_404_RESPONSE, status=404
    )

    async with _client_for(httpserver)(token="test-token") as client:
        with pytest.raises(NotFoundError, match="Not Found"):
            await client.get_repo("i-safonoff", "missing")


async def test_list_issues_follows_a_real_link_header_across_pages(
    httpserver: HTTPServer,
) -> None:
    page2_url = httpserver.url_for("/repos/octo/repo/issues?page=2")

    httpserver.expect_request("/repos/octo/repo/issues", query_string="").respond_with_json(
        [REAL_ISSUE_RESPONSE],
        headers={"Link": f'<{page2_url}>; rel="next"'},
    )
    second_issue = {**REAL_ISSUE_RESPONSE, "id": 999, "number": 1, "title": "second page"}
    httpserver.expect_request("/repos/octo/repo/issues", query_string="page=2").respond_with_json(
        [second_issue]
    )

    async with _client_for(httpserver)(token="test-token") as client:
        issues = [issue async for issue in client.list_issues("octo", "repo")]

    assert [i.number for i in issues] == [336340, 1]
    assert isinstance(issues[0], Issue)


async def test_create_issue_sends_the_body_and_parses_the_created_issue(
    httpserver: HTTPServer,
) -> None:
    seen = {}

    def handler(request: Request) -> Response:
        seen["json"] = request.get_json()
        seen["idempotency_key"] = request.headers.get("Idempotency-Key")
        return Response(
            json.dumps(REAL_ISSUE_RESPONSE).encode(), status=201, content_type="application/json"
        )

    httpserver.expect_request("/repos/octo/repo/issues", method="POST").respond_with_handler(
        handler
    )

    async with _client_for(httpserver)(token="test-token") as client:
        issue = await client.create_issue(
            "octo", "repo", NewIssue(title="a new bug", body="steps to reproduce")
        )

    assert seen["json"] == {"title": "a new bug", "body": "steps to reproduce"}
    assert seen["idempotency_key"] is not None
    assert issue.number == 336340
