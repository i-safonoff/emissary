from __future__ import annotations

from pydantic import BaseModel
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request, Response

from emissary import ApiClient, endpoint


class Repo(BaseModel):
    name: str
    stars: int


class NewIssue(BaseModel):
    title: str
    body: str


class Issue(BaseModel):
    number: int
    title: str


def _client_for(httpserver: HTTPServer, **kwargs: object) -> ApiClient:
    class Client(ApiClient):
        base_url = httpserver.url_for("")

        @endpoint("GET", "/repos/{owner}/{name}")
        async def get_repo(self, owner: str, name: str) -> Repo: ...

        @endpoint("POST", "/repos/{owner}/{name}/issues")
        async def create_issue(self, owner: str, name: str, body: NewIssue) -> Issue: ...

        @endpoint("DELETE", "/repos/{owner}/{name}")
        async def delete_repo(self, owner: str, name: str) -> None: ...

    return Client(**kwargs)  # type: ignore[arg-type]


async def test_path_params_fill_the_url_and_response_parses_into_the_model(
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_request("/repos/octocat/hello-world").respond_with_json(
        {"name": "hello-world", "stars": 42}
    )

    async with _client_for(httpserver) as client:
        repo = await client.get_repo("octocat", "hello-world")  # type: ignore[attr-defined]

    assert repo == Repo(name="hello-world", stars=42)


async def test_path_params_are_url_escaped(httpserver: HTTPServer) -> None:
    seen = {}

    def handler(request: Request) -> Response:
        # request.path is WSGI's PATH_INFO, which the server decodes before
        # this handler ever sees it -- %2F and a literal / are already
        # indistinguishable by then. RAW_URI is the actual bytes that
        # arrived on the wire, which is the thing quote() is responsible
        # for and the only place this is actually verifiable.
        seen["raw_uri"] = request.environ.get("RAW_URI")
        return Response(b'{"name": "a/b", "stars": 0}', status=200, content_type="application/json")

    httpserver.expect_request("/repos/octocat/a/b").respond_with_handler(handler)

    async with _client_for(httpserver) as client:
        repo = await client.get_repo("octocat", "a/b")  # type: ignore[attr-defined]

    assert seen["raw_uri"] == "/repos/octocat/a%2Fb"
    assert repo.name == "a/b"


async def test_a_basemodel_parameter_becomes_the_json_body(httpserver: HTTPServer) -> None:
    seen = {}

    def handler(request: Request) -> Response:
        seen["json"] = request.get_json()
        body = b'{"number": 1, "title": "bug"}'
        return Response(body, status=201, content_type="application/json")

    httpserver.expect_request(
        "/repos/octocat/hello-world/issues", method="POST"
    ).respond_with_handler(handler)

    async with _client_for(httpserver) as client:
        issue = await client.create_issue(  # type: ignore[attr-defined]
            "octocat", "hello-world", NewIssue(title="bug", body="it broke")
        )

    assert seen["json"] == {"title": "bug", "body": "it broke"}
    assert issue == Issue(number=1, title="bug")


async def test_no_return_annotation_discards_the_body(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/repos/octocat/hello-world", method="DELETE").respond_with_data(
        status=204
    )

    async with _client_for(httpserver) as client:
        result = await client.delete_repo("octocat", "hello-world")  # type: ignore[attr-defined]

    assert result is None
