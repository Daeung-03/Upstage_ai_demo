from __future__ import annotations

import io
import mimetypes
import re
from html.parser import HTMLParser

from pydantic import BaseModel
from pypdf import PdfReader, PdfWriter

from ai.services.upstage import UpstageClient

DOCUMENT_PARSE_PATH = "/document-digitization"
MODEL = "document-parse"
DEFAULT_CONTENT_TYPE = "application/pdf"
# Default mode: "enhanced" — VLM 기반, 표/체크박스/차트 정밀도↑ (페이지 비용↑).
# 운영 비용에 민감하면 호출자가 mode="standard"로 override 가능.
# 가능한 값: "standard" (기본 OCR), "enhanced" (VLM), "auto" (자동 선택).
DEFAULT_PARSE_MODE = "enhanced"
HTML_EXTS = (".html", ".htm")
# Upstage Document Parse 동기 엔드포인트는 1회 100페이지 한도(초과 시 413).
# 100p 초과 PDF 는 _split_pdf 로 ≤100p 청크로 나눠 호출 후 결과를 병합한다.
MAX_SYNC_PAGES = 100

# heading 시작 토큰이 단독으로 한 줄 차지하면 (빈 heading) 정리 시 제거.
# class 본문에서 lookup 되므로 class 위에 정의해야 forward-reference 회피.
HEADING_TAGS_ALONE = {"# ", "## ", "### ", "#### ", "##### ", "###### "}


class _HTMLTextExtractor(HTMLParser):
    """HTML → markdown. Heading/list/strong 등 구조 보존.

    Solar Pro 3가 약관의 섹션 위계 ("## 5. 보증 및 책임의 제한")를 인식할 수 있도록
    의미 있는 tag를 markdown으로 변환. 단순 plain text로 평탄화하면 long-doc 추출 시
    섹션 단위 navigation이 안 됨 (실측: Netflix HTML liability 0/6 → markdown 변환으로 회복).
    """

    HEADING_TAGS = {"h1": "# ", "h2": "## ", "h3": "### ", "h4": "#### ", "h5": "##### ", "h6": "###### "}
    BLOCK_TAGS = {"p", "br", "div", "tr", "section", "article"}
    SKIP_TAGS = {"script", "style", "noscript"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip_depth = 0
        self.in_strong = 0  # <strong>/<b> 중첩 카운터

    def handle_starttag(self, tag: str, attrs):
        if tag in self.SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth > 0:
            return
        if tag in self.HEADING_TAGS:
            self.parts.append("\n\n" + self.HEADING_TAGS[tag])
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in ("strong", "b"):
            self.in_strong += 1
            self.parts.append("**")
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str):
        if tag in self.SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth > 0:
            return
        if tag in self.HEADING_TAGS:
            self.parts.append("\n")
        elif tag in ("strong", "b"):
            self.in_strong = max(0, self.in_strong - 1)
            self.parts.append("**")

    def handle_data(self, data: str):
        if self.skip_depth == 0:
            text = data.strip()
            if text:
                self.parts.append(text + " ")

    def get_text(self) -> str:
        raw = "".join(self.parts)
        # 4+ 연속 줄바꿈 → 2개로 정리 (markdown 단락 구분 유지)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        # 공백 정리: 한 줄 안에서 연속 공백 1개로
        lines = [re.sub(r" +", " ", line).strip() for line in raw.split("\n")]
        # 헤더 행이 공백 헤더 ("## ") 만 있으면 제거
        return "\n".join(line for line in lines if line and line not in HEADING_TAGS_ALONE).strip()


def _guess_content_type(filename: str) -> str:
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or DEFAULT_CONTENT_TYPE


class ParsedElement(BaseModel):
    id: int
    page: int
    category: str
    text: str
    # bbox는 0-1 normalized (페이지 width/height 곱해서 pixel로 변환)
    bbox: tuple[float, float, float, float] | None = None  # (x0, y0, x1, y1)


class DocumentParseResult(BaseModel):
    markdown: str
    elements: list[ParsedElement]


def _coords_to_bbox(coords: list[dict]) -> tuple[float, float, float, float] | None:
    if not coords:
        return None
    xs = [c["x"] for c in coords]
    ys = [c["y"] for c in coords]
    return (min(xs), min(ys), max(xs), max(ys))


def _element_text(content) -> str:
    """ParsedElement.text 추출 — Upstage 응답이 markdown 에만 채우므로 그쪽 우선.

    응답 shape: {"html": str, "markdown": str, "text": str}. 관찰 결과 text 는
    항상 빈 문자열, markdown 에 실제 OCR 텍스트가 들어있다.
    """
    if not isinstance(content, dict):
        return ""
    for key in ("markdown", "text", "html"):
        v = content.get(key)
        if v:
            return v
    return ""


def _parse_html_directly(file_bytes: bytes) -> DocumentParseResult:
    """HTML 입력은 Document Parse(415 Unsupported)를 우회하고 직접 텍스트 추출.

    이미 구조화된 입력이라 OCR/layout이 불필요. bbox는 None(없음)으로 두고
    quote 매칭은 substring으로 fallback (extract 단계의 _find_element_for_quote).
    """
    parser = _HTMLTextExtractor()
    parser.feed(file_bytes.decode("utf-8", errors="ignore"))
    markdown = parser.get_text()
    if not markdown:
        raise ValueError("HTML returned empty text content")
    # 단일 element (페이지 1, bbox 없음) — extract bbox enrichment는 element.text substring 매칭으로 동작
    element = ParsedElement(id=1, page=1, category="paragraph", text=markdown, bbox=None)
    return DocumentParseResult(markdown=markdown, elements=[element])


def _split_pdf(file_bytes: bytes, chunk_pages: int) -> list[bytes]:
    """PDF 를 chunk_pages 페이지 단위로 분할.

    페이지 수가 chunk_pages 이하면 [원본] 그대로 반환. PDF 가 아니거나 손상돼
    PdfReader 가 실패하면 예외 전파 — 호출자가 단일 호출로 fallback.
    """
    reader = PdfReader(io.BytesIO(file_bytes))
    total = len(reader.pages)
    if total <= chunk_pages:
        return [file_bytes]
    chunks: list[bytes] = []
    for start in range(0, total, chunk_pages):
        writer = PdfWriter()
        for i in range(start, min(start + chunk_pages, total)):
            writer.add_page(reader.pages[i])
        buf = io.BytesIO()
        writer.write(buf)
        chunks.append(buf.getvalue())
    return chunks


async def _parse_one(
    client: UpstageClient, file_bytes: bytes, filename: str, mode: str
) -> tuple[str, list[dict]]:
    """Document Parse 단일 호출 → (markdown, elements_raw)."""
    files = {"document": (filename, file_bytes, _guess_content_type(filename))}
    data = {
        "model": MODEL,
        "output_formats": '["markdown"]',
        "coordinates": "true",
        "ocr": "auto",
        "mode": mode,
    }
    raw = await client.post_multipart(DOCUMENT_PARSE_PATH, files=files, data=data)
    markdown = (raw.get("content") or {}).get("markdown", "")
    elements_raw = raw.get("elements") or []
    if not markdown and not elements_raw:
        raise ValueError("Document Parse returned empty content")
    return markdown, elements_raw


async def parse_document(
    client: UpstageClient,
    *,
    file_bytes: bytes,
    filename: str,
    mode: str = DEFAULT_PARSE_MODE,
) -> DocumentParseResult:
    """파일을 markdown + elements로 변환.

    - PDF/이미지: Upstage Document Parse 호출 (OCR + layout). 좌표는 0-1 normalized.
      100페이지 초과 PDF 는 동기 엔드포인트 한도(100p) 때문에 ≤100p 청크로 나눠
      호출하고, markdown 을 이어붙이며 element.page 를 청크 오프셋만큼 보정한다.
    - HTML: 직접 텍스트 추출 (Document Parse 미지원 + 이미 구조화됨).
    mode 인자는 Document Parse 모드 (HTML 경로에서는 무시됨).
    """
    if filename.lower().endswith(HTML_EXTS):
        return _parse_html_directly(file_bytes)

    try:
        chunks = _split_pdf(file_bytes, MAX_SYNC_PAGES)
    except Exception:
        # PDF 가 아니거나(이미지 등) 손상 → 분할 없이 단일 호출, API 가 판정.
        chunks = [file_bytes]

    markdown_parts: list[str] = []
    elements: list[ParsedElement] = []
    for idx, chunk in enumerate(chunks):
        page_offset = idx * MAX_SYNC_PAGES
        chunk_markdown, elements_raw = await _parse_one(client, chunk, filename, mode)
        markdown_parts.append(chunk_markdown)
        for e in elements_raw:
            elements.append(
                ParsedElement(
                    id=len(elements) + 1,  # 청크 병합 시 id 재부여 (1-base 연속)
                    page=e["page"] + page_offset,
                    category=e["category"],
                    # Upstage 응답은 content.markdown 에 실제 텍스트를 담고,
                    # content.text 는 항상 빈 문자열. markdown 우선, 비면 text fallback.
                    text=_element_text(e.get("content")),
                    bbox=_coords_to_bbox(e.get("coordinates") or []),
                )
            )
    return DocumentParseResult(markdown="\n\n".join(markdown_parts), elements=elements)
