# 캐롯 보험상품 약관 PDF fetcher 설계

- 날짜: 2026-05-16
- 범위: `scripts/fetch_public_terms.py` 에 보험 도메인 fetcher 추가

## 배경 / 문제

보험(`TermDomain.INSURANCE`) 도메인 인프라는 이미 갖춰져 있다 — sub-category vocab
(`app/models/sub_category.py`), golden 템플릿 빌더(`scripts/build_insurance_golden_template.py`),
샘플 골든(`data/fixtures/sample_insurance_golden_template.json`). 그러나 OTT/FINANCE/AI
와 달리 보험은 "fetch → fixture → bulk_upload → DB" 파이프라인 입력이 **하나도 없다**:
`fetch_public_terms.py` 에 보험 fetcher 없음, `data/fixtures/` 에 보험 약관 없음.

## 조사 결과 (2026-05-16 웹서치)

후보 3사 중 캐롯만 깨끗하게 fetch 가능:

- **카카오페이손해보험** — 완전 CSR SPA(`id="root"` 빈 셸). 정적 약관 URL 미발견,
  API 역분석 필요 → 범위 제외.
- **토스 미니보험** — 비바리퍼블리카는 **보험대리점(GA)**, 보험사 아님. 미니보험은
  삼성화재·처브 등이 인수 → "토스" 브랜드 자체 약관 PDF가 존재하지 않음 → 범위 제외.
- **캐롯손해보험** — 상품 약관 PDF가 정적 CDN(`carrotins.com/cdn/dis/doc/pdf/disclosure/...`)
  에 있어 `urllib` 로 바로 다운로드 가능. 2건 HTTP 200 확인:
  - 캐롯 자동차보험 개인용 약관 (퍼마일 특약 포함) — `car/CA00044001/terms/CA00044001_20240701_01.pdf` (≈4.3MB)
  - 캐롯 해외여행보험 약관 — `general/FA00045001/terms/FA00045001_20230810_01.pdf`

캐롯 공시 listing API 는 CMS(`cms.carrotins.com`) 뒤에 있어 동적 발견 비용이 크다.
→ 기존 fetcher 패턴대로 **URL 하드코딩 + 실패 시 명시적 에러** 채택.

## 설계

### 상품 레지스트리 (하드코딩, 확장 가능)

`fetch_public_terms.py` 모듈 레벨에 캐롯 상품 리스트:

```python
CARROT_PRODUCTS = [
    {
        "stem": "carrot_auto",
        "name": "캐롯 자동차보험",
        "sub_category": "자동차보험",
        "url": "https://www.carrotins.com/cdn/dis/doc/pdf/disclosure/car/"
               "CA00044001/terms/CA00044001_20240701_01.pdf",
    },
    {
        "stem": "carrot_travel",
        "name": "캐롯 해외여행보험",
        "sub_category": "여행자보험",
        "url": "https://www.carrotins.com/cdn/dis/doc/pdf/disclosure/general/"
               "FA00045001/terms/FA00045001_20230810_01.pdf",
    },
]
```

- `sub_category` 는 `RECOMMENDED_SUB_CATEGORIES[TermDomain.INSURANCE]` vocab 과 일치
  ("자동차보험", "여행자보험").
- 운전자·펫 등 추가 상품은 product code 확인 후 튜플 1줄 append 로 확장.

### 다운로드 동작 — `fetch_carrot()`

각 상품마다:

1. PDF 바이너리 다운로드. PDF 가 4MB+ 이므로 기존 `_get()`(timeout 30s) 대신
   **timeout 60s 전용 헬퍼 `_get_pdf(url)`** 사용. Wayback 헬퍼가 60s 쓰는 것과 동일.
2. **검증**: 응답 첫 5바이트가 `b"%PDF-"` 인지 확인. 아니면 (stale URL → 404 HTML
   에러페이지 등) `RuntimeError(f"Carrot {name}: not a PDF at {url} (URL changed?)")`.
3. `data/fixtures/<stem>_terms.pdf` 로 저장.

파일 출력: `carrot_auto_terms.pdf`, `carrot_travel_terms.pdf`. `<stem>_terms.<ext>`
컨벤션 준수. HTML 래핑 없음 — PDF 는 `services/parse.py` 의 Document Parse 단이 처리하고
`single_run.py` 가 이미 `.pdf` 를 `.html` 보다 우선한다(Netflix 와 동일 경로).

### 에러 핸들링 — fail-fast

상품 한 건이라도 다운로드/검증 실패 시 즉시 `RuntimeError` raise. 기존 fetcher 전부
동일(부분 성공으로 stale fixture 가 섞이는 것 방지). `urllib` 의 `HTTPError`(404 등)는
그대로 전파 — 호출자에게 충분히 명시적.

### `main()` / 문서

- `main()` 에 `elif service == "carrot": fetch_carrot()` 분기 추가.
- `all` 분기는 그대로 (spotify + wavve 유지) — 보험은 명시적 `carrot` 호출만.
- 모듈 docstring 사용 예시에 `carrot` 줄 추가.
- `data/fixtures/README.md` 의 파일 표 + "추가 방법" 에 캐롯 항목 추가.

### 범위 외

VENDORS 카탈로그 등록, `bulk_upload_fixtures.py` 의 FIXTURES 스펙, golden 시딩은
이번 범위 외(사용자 결정). fetcher 가 fixture PDF 를 만드는 데까지만.

## 테스트

`fetch_public_terms.py` 는 네트워크 의존이라 기존 자동 테스트가 없다. 신규 테스트도
추가하지 않음(현 컨벤션 유지). 검증은 수동:

```
.venv/bin/python scripts/fetch_public_terms.py carrot
# → data/fixtures/carrot_auto_terms.pdf, carrot_travel_terms.pdf 생성
# → 각 파일 head -c 5 == "%PDF-"
```
