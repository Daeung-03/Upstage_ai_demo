import io

import pytest

from ai.services.parse import DocumentParseResult, _element_text, parse_document
from ai.services.settings import Settings
from ai.services.upstage import UpstageClient


def test_element_text_prefers_markdown_over_empty_text():
    """관찰: Upstage 응답이 content.text='' / content.markdown='실제 텍스트' 형태로 옴.

    기존 코드는 text 만 보고 모든 element 가 빈 텍스트로 들어가 bbox 매칭이 망가졌다.
    """
    assert _element_text({"text": "", "markdown": "실제 텍스트", "html": ""}) == "실제 텍스트"


def test_element_text_falls_back_to_text_when_markdown_empty():
    """방어용 fallback: markdown 비면 text 사용."""
    assert _element_text({"text": "fallback", "markdown": "", "html": ""}) == "fallback"


def test_element_text_handles_missing_content():
    assert _element_text(None) == ""
    assert _element_text({}) == ""


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


async def test_parse_document_uses_markdown_when_text_field_empty(httpx_mock, settings):
    """실제 Upstage 응답을 시뮬레이트: content.text 는 항상 '' 로 비어있고 markdown 에 실 텍스트.

    회귀 가드: 이전엔 element.text 가 모두 '' 로 들어가 _find_element_for_quote 가
    빈 element 에 잘못 매칭되어 모든 citation 이 같은 bbox 를 가졌다.
    """
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/document-digitization",
        json={
            "content": {"markdown": "# 약관\n구독 자동 갱신됩니다."},
            "elements": [
                {
                    "id": 0, "page": 1, "category": "header",
                    "content": {"text": "", "markdown": "# 약관", "html": ""},
                    "coordinates": [
                        {"x": 0.0, "y": 0.0}, {"x": 0.1, "y": 0.0},
                        {"x": 0.1, "y": 0.05}, {"x": 0.0, "y": 0.05},
                    ],
                },
                {
                    "id": 1, "page": 1, "category": "paragraph",
                    "content": {"text": "", "markdown": "구독 자동 갱신됩니다.", "html": ""},
                    "coordinates": [
                        {"x": 0.1, "y": 0.2}, {"x": 0.5, "y": 0.2},
                        {"x": 0.5, "y": 0.3}, {"x": 0.1, "y": 0.3},
                    ],
                },
            ],
            "usage": {"pages": 1},
        },
    )
    async with UpstageClient(settings) as client:
        result = await parse_document(client, file_bytes=b"%PDF", filename="t.pdf")
    assert result.elements[0].text == "# 약관"
    assert result.elements[1].text == "구독 자동 갱신됩니다."


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
