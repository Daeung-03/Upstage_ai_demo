# Fixtures

E2E / 평가용 실제 약관 PDF·HTML 보관소. 모두 `.gitignore` 대상 — 각 환경에서
원본을 다시 받아 배치한다.

## 파일

| 서비스 | 파일 | 형식 | 골든 라벨 |
|--------|------|------|-----------|
| Netflix | `netflix_terms.pdf` | PDF (Document Parse) | `netflix_golden.json` |
| Netflix | `netflix_terms.html` | HTML (parse 단 우회) | `netflix_golden.json` |
| Spotify | `spotify_terms.html` | HTML | `spotify_golden.json` |
| Wavve | `wavve_terms.html` | HTML (서비스 + 유료 결합) | `wavve_golden.json` |
| Coupang Play | `coupang_play_terms.html` | HTML (이용 기준 + 유료 결합) | `coupang_play_golden.json` |
| TVING | `tving_terms.html` | HTML (서비스 + 유료 탭 결합) | `tving_golden.json` |

## 추가 방법

### Netflix
브라우저에서 https://help.netflix.com/ko/legal/termsofuse 열어 PDF 출력 →
`netflix_terms.pdf` 로 저장. HTML 버전은 동일 URL을 curl로 받아 본문만 추출
(현재는 임시 스크립트로 생성, 추후 `scripts/fetch_public_terms.py` 로 통합 예정).

### Spotify · Wavve
    .venv/bin/python scripts/fetch_public_terms.py spotify
    .venv/bin/python scripts/fetch_public_terms.py wavve
    .venv/bin/python scripts/fetch_public_terms.py all      # spotify + wavve

### Coupang Play
React가 `web.coupangstreaming.com/tnc/` iframe을 띄우는 구조라서, iframe 원본을
직접 받으면 된다 (Akamai 차단 우회 불필요):

    curl -sL https://web.coupangstreaming.com/tnc/index.html       -o /tmp/coupang_tnc.html
    curl -sL https://web.coupangstreaming.com/tnc/tvod/index.html  -o /tmp/coupang_tnc_tvod.html

두 문서를 `<h2>제N조</h2>` 구조로 결합해 `coupang_play_terms.html` 로 저장
(임시 스크립트 — 추후 `fetch_public_terms.py` 로 통합 예정).

### TVING
SPA(JS 렌더링 필수). Playwright + 모바일 UA로 두 탭(서비스/유료) 모두 캡처:

    uv pip install playwright
    .venv/bin/python -m playwright install chromium
    # 그 후 임시 스크립트로 m.tving.com/guide/term.tving 렌더링
    # → '유료이용약관' 탭 클릭으로 두 번째 문서까지 수집

## 실행

`.env` 에 `UPSTAGE_API_KEY` 설정 후:

    pytest tests/integration -v -m e2e        # 통합 테스트
    .venv/bin/python scripts/single_run.py <fixture_name>   # 단일 실행
    .venv/bin/python scripts/score_against_golden.py /tmp/variance_run_1.json data/fixtures/<service>_golden.json [--semantic]

`single_run.py` 는 `<name>_terms.pdf` 우선, 없으면 `.html` 사용.
