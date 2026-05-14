import io

import pytest

from services.parse import DocumentParseResult, parse_document
from services.settings import Settings
from services.upstage import UpstageClient


@pytest.fixture
def settings(sample_api_key, sample_base_url):
    return Settings(upstage_api_key=sample_api_key, upstage_base_url=sample_base_url)


async def test_parse_document_returns_structured_result(httpx_mock, settings):
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/document-digitization",
        json={
            "apiVersion": "1.1",
            "model": "document-parse-260128",
            "content": {"markdown": "# 이용약관\n\n제1조 (목적)..."},
            "elements": [
                {
                    "id": 1,
                    "page": 1,
                    "category": "heading1",
                    "content": {"text": "이용약관", "markdown": "# 이용약관"},
                    "coordinates": [
                        {"x": 0.125, "y": 0.05},
                        {"x": 0.425, "y": 0.05},
                        {"x": 0.425, "y": 0.08},
                        {"x": 0.125, "y": 0.08},
                    ],
                },
                {
                    "id": 2,
                    "page": 1,
                    "category": "paragraph",
                    "content": {"text": "제1조 (목적)...", "markdown": "제1조 (목적)..."},
                    "coordinates": [
                        {"x": 0.10, "y": 0.10},
                        {"x": 0.50, "y": 0.10},
                        {"x": 0.50, "y": 0.20},
                        {"x": 0.10, "y": 0.20},
                    ],
                },
            ],
            "usage": {"pages": 1},
        },
    )
    fake_pdf = io.BytesIO(b"%PDF-1.4 fake content")
    async with UpstageClient(settings) as client:
        result = await parse_document(client, file_bytes=fake_pdf.getvalue(), filename="t.pdf")
    assert isinstance(result, DocumentParseResult)
    assert "이용약관" in result.markdown
    assert len(result.elements) == 2
    assert result.elements[0].page == 1
    # bbox는 0-1 normalized
    assert result.elements[0].bbox == (0.125, 0.05, 0.425, 0.08)


async def test_parse_document_raises_on_empty_response(httpx_mock, settings):
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/document-digitization",
        json={"content": {"markdown": ""}, "elements": []},
    )
    async with UpstageClient(settings) as client:
        with pytest.raises(ValueError, match="empty"):
            await parse_document(client, file_bytes=b"", filename="empty.pdf")


async def test_parse_document_uses_html_mime_for_html_files(httpx_mock, settings):
    """HTML 파일은 application/pdf가 아닌 text/html로 전송되어야 함."""
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/document-digitization",
        json={"content": {"markdown": "# Terms"}, "elements": []},
    )
    async with UpstageClient(settings) as client:
        await parse_document(client, file_bytes=b"<html><body>terms</body></html>", filename="terms.html")
    req = httpx_mock.get_request()
    body = req.content.decode("utf-8", errors="ignore")
    assert "text/html" in body


async def test_parse_document_mode_parameter_passes_through(httpx_mock, settings):
    """mode 인자가 multipart form data에 그대로 전달되어야 함 (운영 비용 조절 가능)."""
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/document-digitization",
        json={"content": {"markdown": "# t"}, "elements": []},
    )
    async with UpstageClient(settings) as client:
        await parse_document(client, file_bytes=b"%PDF", filename="t.pdf", mode="standard")
    req = httpx_mock.get_request()
    body = req.content.decode("utf-8", errors="ignore")
    assert 'name="mode"' in body
    # form-data part 형식: name="mode"\r\n\r\nstandard
    assert "standard" in body
    assert "enhanced" not in body
