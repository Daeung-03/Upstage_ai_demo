# Diagnosis — coupang_play (5 runs)

## Category counts

| 분류 | 카운트 |
|---|---|
| D. model never extracted (golden has value) | 18 |
| A. both null | 10 |
| X. ambiguous | 10 |
| A. consensus matches golden | 6 |
| C. model variance (no consensus) | 5 |
| B. consensus disagrees with golden | 2 |

## ⚠️ Category B (golden 의심 — 모델 consensus ≠ golden)

| 필드 | golden expected | 모델 consensus | agreement | runs |
|---|---|---|---|---|
| `disputes.jurisdiction_clause` | `'민사소송법상 관할법원'` | `'민사소송법'` | 100% | '민사소송법', '민사소송법', '민사소송법', '민사소송법', '민사소송법' |
| `unfair_clause_flags` | `['POST-01', 'POST-03', 'POST-04', 'POST-05', '면책/손배 제한', '약관 일방 변경권', '의사표시_의제', '환불 거부 (시청 시 청약철회 권리 소멸)']` | `['의사표시_의제']` | 80% | ['의사표시_의제'], ['의사표시_의제'], ['면책_손배_제한', '의사표시_의제'], ['의사표시_의제'], ['의사표시_의제'] |

## D. 모델 추출 실패 (golden 정답일 가능성 高 — 모델/프롬프트 개선 후보)

| 필드 | golden expected |
|---|---|
| `pricing.billing_cycle` | `'monthly'` |
| `pricing.auto_renewal_enabled` | `True` |
| `pricing.auto_renewal_consent` | `'opt_in_explicit'` |
| `pricing.price_change_notice_channels` | `['email', 'in_app_banner']` |
| `free_trial.auto_convert_to_paid` | `True` |
| `cancellation.notice_period_days` | `0` |
| `cancellation.penalty_present` | `False` |
| `cancellation.cooling_off_refund_days` | `7` |
| `cancellation.cooling_off_conditions` | `'콘텐츠 미시청'` |
| `cancellation.third_party_cancellation_required` | `True` |
| `terms_changes.price_change_explicit_consent` | `True` |
| `data_usage.marketing_consent` | `'opt_out_available'` |
| `data_usage.cross_border_transfer` | `False` |
| `liability.indirect_damages_excluded` | `True` |
| `account.minimum_age` | `19` |
| `account.sharing_restrictions` | `'household_only'` |
| `service.regional_content_restriction` | `True` |
| `service.availability_disclaimer` | `True` |

## E. Over-extraction (golden null + 모델 값)

_없음_

## C. 모델 흔들림 (variance, no consensus < 50%)

| 필드 | golden | 모델 5 runs |
|---|---|---|
| `terms_changes.notice_channels` | `['email', 'in_app_banner']` | ['email', 'sms', 'app_push', ' · ['app_push', 'web_notice'] · ['web_notice'] · ['web_notice', 'app_push'] · ['app_push', 'email', 'sms', ' |
| `data_usage.third_party_recipients` | `['law_enforcement', 'sellers', 'shipping_carriers']` | None · ['수사기관', '정부기관', '판매자', '배송업체' · ['수사기관', '정부기관', '판매자', '배송업체' · ['수사기관', '정부기관', '판매자', '배송업체' · None |
| `data_usage.third_party_purposes` | `['law_enforcement', 'transaction_fulfillment', 'fraud_prevention']` | None · ['법령 위반 확인', '거래 및 배송'] · ['법적 절차', '거래 및 배송', '마케팅', '서 · ['법적 절차', '부정행위 확인', '거래 및 배송' · None |
| `liability.compensation_description` | `'서비스 중단으로 회원이 입은 손해에 대해 배상 (회사 무과실 입증 시 면책)'` | None · '천재지변 또는 이에 준하는 불가항력, 컴퓨터 등 정보 · '천재지변 또는 이에 준하는 불가항력, 컴퓨터 등 정보 · '천재지변, 정보통신설비 보수·점검·교체·고장·통신두절 · '천재지변 또는 이에 준하는 불가항력, 컴퓨터 등 정보 |
| `liability.force_majeure_scope` | `'천재지변 또는 이에 준하는 불가항력, 컴퓨터 등 정보통신설비의 보수점검·교체, 고장, 통신의 두절 등의 사유'` | '천재지변 또는 이에 준하는 불가항력' · '천재지변 또는 이에 준하는 불가항력, 컴퓨터 등 정보 · '천재지변 또는 이에 준하는 불가항력, 컴퓨터 등 정보 · '천재지변, 정보통신설비 보수·점검·교체·고장·통신두절 · '천재지변 또는 이에 준하는 불가항력' |
