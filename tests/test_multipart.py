from __future__ import annotations

from pydantic import BaseModel
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request, Response

from emissary import ApiClient, UploadFile, endpoint
from emissary._forms import split_multipart


class Attachment(BaseModel):
    title: str
    file: UploadFile
    description: str | None = None


def test_split_multipart_separates_the_file_field_from_form_fields() -> None:
    model = Attachment(
        title="a report",
        file=UploadFile(filename="report.csv", content=b"a,b,c\n1,2,3", content_type="text/csv"),
    )

    data, files = split_multipart(model)

    assert data == {"title": "a report"}
    assert files == {"file": ("report.csv", b"a,b,c\n1,2,3", "text/csv")}


def test_split_multipart_drops_none_fields() -> None:
    model = Attachment(
        title="a report",
        file=UploadFile(filename="x.txt", content=b"x", content_type="text/plain"),
        description=None,
    )

    data, _files = split_multipart(model)

    assert "description" not in data


async def test_body_encoding_multipart_sends_a_real_multipart_request(
    httpserver: HTTPServer,
) -> None:
    seen = {}

    def handler(request: Request) -> Response:
        seen["content_type"] = request.headers.get("Content-Type", "")
        seen["form"] = request.form.to_dict()
        uploaded = request.files["file"]
        seen["filename"] = uploaded.filename
        seen["file_content"] = uploaded.read()
        seen["file_content_type"] = uploaded.content_type
        return Response(b"{}", status=200, content_type="application/json")

    httpserver.expect_request("/attachments", method="POST").respond_with_handler(handler)

    class Client(ApiClient):
        base_url = httpserver.url_for("")

        @endpoint("POST", "/attachments", body_encoding="multipart")
        async def upload(self, body: Attachment) -> None: ...

    async with Client() as client:
        await client.upload(  # type: ignore[attr-defined]
            Attachment(
                title="a report",
                file=UploadFile(
                    filename="report.csv", content=b"a,b,c\n1,2,3", content_type="text/csv"
                ),
            )
        )

    assert seen["content_type"].startswith("multipart/form-data")
    assert seen["form"] == {"title": "a report"}
    assert seen["filename"] == "report.csv"
    assert seen["file_content"] == b"a,b,c\n1,2,3"
    assert seen["file_content_type"] == "text/csv"
