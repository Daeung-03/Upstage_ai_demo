# Diagnosis — watcha (5 runs)

## Category counts

| 분류 | 카운트 |
|---|---|
| A. consensus matches golden | 16 |
| D. model never extracted (golden has value) | 13 |
| C. model variance (no consensus) | 8 |
| A. both null | 6 |
| X. ambiguous | 4 |
| B. consensus disagrees with golden | 2 |
| E. over-extraction (golden null, model invents) | 2 |

## ⚠️ Category B (golden 의심 — 모델 consensus ≠ golden)

| 필드 | golden expected | 모델 consensus | agreement | runs |
|---|---|---|---|---|
| `cancellation.penalty_description` | `'중도 해지 시 결제금액의 10% (이용대금 별도 공제: VOD 1편당 2,000원)'` | `'결제금액의 10%'` | 60% | '결제금액의 10%', '결제금액의 10%', '결제금액의 10% 위약금', '결제금액의 10% 위약금', '결제금액의 10%' |
| `liability.force_majeure_scope` | `'천재지변 또는 이에 준하는 불가항력, 회원 귀책, 회사 관리영역 외 공중통신선로 장애, 기타 회사 귀책사유 없는 통신 장애'` | `'천재지변 또는 이에 준하는 불가항력'` | 60% | '천재지변 또는 이에 준하는 불가항력', '천재지변 또는 이에 준하는 불가항력', '천재지변 또는 이에 준하는 불가항력', '천재지변, 국가비상사태, 정전 등 회사가 통제할 수 없는 불가항력적 사, None |

## D. 모델 추출 실패 (golden 정답일 가능성 高 — 모델/프롬프트 개선 후보)

| 필드 | golden expected |
|---|---|
| `pricing.price_change_notice_days` | `30` |
| `pricing.price_change_notice_channels` | `['web_notice']` |
| `free_trial.auto_convert_to_paid` | `True` |
| `free_trial.cancel_required_before_end` | `True` |
| `cancellation.cooling_off_refund_days` | `7` |
| `cancellation.cooling_off_conditions` | `'이용 내역 없음'` |
| `cancellation.third_party_cancellation_required` | `True` |
| `terms_changes.price_change_explicit_consent` | `True` |
| `liability.damages_cap_description` | `'직접 손해는 실손 배상. 간접손해·기대이익 상실·서비스 신뢰 손실 등 제외.'` |
| `account.minimum_age` | `18` |
| `account.sharing_restrictions` | `'household_only'` |
| `service.regional_content_restriction` | `True` |
| `service.availability_disclaimer` | `True` |

## E. Over-extraction (golden null + 모델 값)

| 필드 | 모델 consensus | agreement |
|---|---|---|
| `data_usage.collected_categories` | `['시청 기록', '콘텐츠 이용 정보', '서비스 이용 환경', '결제 정보', '계정 정보']` | 20% |
| `disputes.governing_law` | `'대한민국 법률'` | 100% |

## C. 모델 흔들림 (variance, no consensus < 50%)

| 필드 | golden | 모델 5 runs |
|---|---|---|
| `cancellation.method_description` | `'온라인 셀프 해지 (정기결제 해지 또는 중도 해지)'` | '정기결제 해지는 결제주기가 종료됨과 동시에 계약이 해 · '유료서비스 이용계약을 체결한 후 다음 중 어느 하나의 · '정기결제 해지는 결제주기 종료 시 자동 해지, 중도  · '회원은 서비스 홈페이지 또는 앱을 통해 청약철회 및  · '온라인(웹사이트) 청약철회' |
| `cancellation.notice_period_days` | `0` | 0 · None · None · 7 · 7 |
| `terms_changes.notice_channels` | `['web_notice']` | ['web_notice'] · ['web_notice', 'email'] · ['web_notice'] · ['email', 'web_notice', 'in_ap · None |
| `data_usage.third_party_sharing` | `True` | True · False · False · True · None |
| `data_usage.third_party_recipients` | `['관계기관 (수사목적)', '위탁사 (서비스 제공)']` | ['law enforcement agencies'] · None · ['관계사', '업무수탁자'] · ['수사기관', '통계기관', '업무수탁자', '요금정 · None |
| `data_usage.third_party_purposes` | `['수사', '본인확인', '서비스 위탁', '요금정산', '통계/연구']` | ['investigative'] · None · ['service provision', 'conveni · ['수사', '통계·연구', '서비스 제공·위탁', ' · None |
| `data_usage.marketing_use` | `True` | True · False · False · True · None |
| `liability.compensation_description` | `'회사 귀책 서비스 중단 시 이용기간 무료 연장 (24시간 초과 시 초과분의 2배 추가)'` | '사업자의 책임 있는 사유로 인한 서비스 중지 또는 장 · None · '서비스 중지·장애시간만큼 무료로 서비스 이용기간 연장 · '서비스 중지·장애시간에 해당하는 이용기간 연장' · '서비스 중지•장애시간만큼 무료로 서비스 이용기간 연장 |
