# Diagnosis — coupang_play (5 runs)

## Category counts

| 분류 | 카운트 |
|---|---|
| D. model never extracted (golden has value) | 15 |
| A. both null | 10 |
| X. ambiguous | 8 |
| A. consensus matches golden | 8 |
| C. model variance (no consensus) | 7 |
| B. consensus disagrees with golden | 3 |

## ⚠️ Category B (golden 의심 — 모델 consensus ≠ golden)

| 필드 | golden expected | 모델 consensus | agreement | runs |
|---|---|---|---|---|
| `data_usage.marketing_use` | `True` | `False` | 60% | False, False, False, None, None |
| `disputes.jurisdiction_clause` | `'민사소송법상 관할법원'` | `'민사소송법'` | 80% | '민사소송법', '민사소송법', '민사소송법', '민사소송법상 관할법원', '민사소송법' |
| `unfair_clause_flags` | `['POST-01', 'POST-03', 'POST-04', 'POST-05', '면책/손배 제한', '약관 일방 변경권', '의사표시_의제', '환불 거부 (시청 시 청약철회 권리 소멸)']` | `['의사표시_의제']` | 100% | ['의사표시_의제'], ['의사표시_의제'], ['의사표시_의제'], ['의사표시_의제'], ['의사표시_의제'] |

## D. 모델 추출 실패 (golden 정답일 가능성 高 — 모델/프롬프트 개선 후보)

| 필드 | golden expected |
|---|---|
| `pricing.billing_cycle` | `'monthly'` |
| `pricing.price_change_notice_channels` | `['email', 'in_app_banner']` |
| `cancellation.notice_period_days` | `0` |
| `cancellation.penalty_present` | `False` |
| `cancellation.cooling_off_refund_days` | `7` |
| `cancellation.cooling_off_conditions` | `'콘텐츠 미시청'` |
| `cancellation.third_party_cancellation_required` | `True` |
| `terms_changes.price_change_explicit_consent` | `True` |
| `data_usage.cross_border_transfer` | `False` |
| `liability.damages_cap_present` | `False` |
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
| `cancellation.method_description` | `'설정 > 구독관리 (앱/웹) 또는 앱스토어 구독관리'` | None · '회원은 언제든지 탈퇴함으로써 본 서비스 이용을 해지할 · '와우 멤버십 서비스 해지 시 앱/웹에서 탈퇴 요청' · '앱/웹을 통한 탈퇴' · '와우 멤버십 서비스 탈퇴 또는 쿠팡 이용 약관 탈퇴를 |
| `terms_changes.notice_channels` | `['email', 'in_app_banner']` | ['email', 'sms', 'app_push', ' · ['app_push', 'email', 'sms', ' · ['app_push', 'web_notice'] · ['web_notice'] · ['app_push', 'web_notice', 'em |
| `data_usage.collected_categories` | `None` | None · ['성명', '주소', '전화번호', '전자우편주소', · ['purchase history', 'payment  · None · ['이름', '주소', '전화번호', '이메일', '결 |
| `data_usage.third_party_recipients` | `['law_enforcement', 'sellers', 'shipping_carriers']` | None · ['수사기관', '정부기관', '판매자', '배송업체' · ['수사기관', '정부기관', '판매자', '배송업체' · None · ['수사기관', '정부기관', '판매자', '배송업체' |
| `data_usage.third_party_purposes` | `['law_enforcement', 'transaction_fulfillment', 'fraud_prevention']` | None · ['수사', '법령 위반 확인', '거래 및 배송',  · ['법령 위반 확인', '거래 및 배송', '수사기관  · None · ['수사기관 요청', '법령 위반 확인', '거래 및  |
| `liability.compensation_description` | `'서비스 중단으로 회원이 입은 손해에 대해 배상 (회사 무과실 입증 시 면책)'` | None · '천재지변 또는 이에 준하는 불가항력, 컴퓨터 등 정보 · '천재지변 또는 이에 준하는 불가항력, 컴퓨터 등 정보 · '천재지변, 정보통신설비 보수점검·교체·고장·통신두절  · '천재지변, 정보통신설비 고장, 통신두절 등 불가항력  |
| `liability.force_majeure_scope` | `'천재지변 또는 이에 준하는 불가항력, 컴퓨터 등 정보통신설비의 보수점검·교체, 고장, 통신의 두절 등의 사유'` | '천재지변 또는 이에 준하는 불가항력' · '천재지변 또는 이에 준하는 불가항력, 컴퓨터 등 정보 · '천재지변 또는 이에 준하는 불가항력, 컴퓨터 등 정보 · '천재지변, 정보통신설비 보수점검·교체·고장·통신두절  · '천재지변 또는 이에 준하는 불가항력' |
