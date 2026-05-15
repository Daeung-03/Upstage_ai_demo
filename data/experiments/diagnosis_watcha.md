# Diagnosis — watcha (5 runs)

## Category counts

| 분류 | 카운트 |
|---|---|
| A. consensus matches golden | 14 |
| D. model never extracted (golden has value) | 13 |
| C. model variance (no consensus) | 8 |
| B. consensus disagrees with golden | 7 |
| A. both null | 5 |
| X. ambiguous | 3 |
| E. over-extraction (golden null, model invents) | 1 |

## ⚠️ Category B (golden 의심 — 모델 consensus ≠ golden)

| 필드 | golden expected | 모델 consensus | agreement | runs |
|---|---|---|---|---|
| `cancellation.penalty_description` | `'중도 해지 시 결제금액의 10% (이용대금 별도 공제: VOD 1편당 2,000원)'` | `'결제금액의 10%'` | 80% | '결제금액의 10%', '위약금(결제금액의 10%)', '결제금액의 10%', '결제금액의 10%', '결제금액의 10%' |
| `cancellation.proration_policy` | `'prorated_refund'` | `'prorated'` | 100% | 'prorated', 'prorated', 'prorated', 'prorated', 'prorated' |
| `terms_changes.user_consent_mechanism` | `'silent_acceptance'` | `'opt_out_available'` | 60% | 'deemed_agreed', 'opt_out_available', 'opt_out_available', 'opt_out_available', 'deemed_agreed' |
| `data_usage.third_party_sharing` | `'AMBIGUOUS'` | `True` | 60% | True, True, False, None, True |
| `data_usage.marketing_use` | `True` | `False` | 60% | True, False, False, None, False |
| `data_usage.cross_border_transfer` | `None` | `False` | 60% | None, False, False, None, False |
| `liability.force_majeure_scope` | `'천재지변 또는 이에 준하는 불가항력, 회원 귀책, 회사 관리영역 외 공중통신선로 장애, 기타 회사 귀책사유 없는 통신 장애'` | `'천재지변, 국가비상사태, 정전 등 회사가 통제할 수 없는 불가항력적 사유'` | 60% | '천재지변 또는 이에 준하는 불가항력', '천재지변, 국가비상사태, 정전 등 회사가 통제할 수 없는 불가항력적 사, '천재지변 또는 이에 준하는 불가항력', '천재지변, 국가비상사태, 정전 등 회사가 통제할 수 없는 불가항력적 사, '천재지변, 국가비상사태, 정전 등 회사가 통제할 수 없는 불가항력적 사 |

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
| `disputes.governing_law` | `'대한민국 법률'` | 100% |

## C. 모델 흔들림 (variance, no consensus < 50%)

| 필드 | golden | 모델 5 runs |
|---|---|---|
| `free_trial.offered` | `True` | True · False · True · None · False |
| `cancellation.method_description` | `'온라인 셀프 해지 (정기결제 해지 또는 중도 해지)'` | '정기결제 해지는 결제주기가 종료됨과 동시에 계약이 해 · '정기결제 해지는 결제주기 종료 시 자동 해지, 중도  · '정기결제 해지는 결제주기 종료 시 자동 해지되며, 다 · '회원 홈페이지 또는 서비스 내 ‘계정’ 페이지에서 해 · '회원은 회사가 인정한 방법을 통해 의사표시를 하여,  |
| `cancellation.notice_period_days` | `0` | 0 · 7 · None · 7 · None |
| `data_usage.collected_categories` | `None` | ['시청 기록', '콘텐츠 이용 정보', '서비스 이용 · None · ['device usage data'] · ['시청 기록', '결제 정보', '계정 정보', '기 · ['서비스 이용에 필요한 최소한의 정보'] |
| `data_usage.third_party_recipients` | `['관계기관 (수사목적)', '위탁사 (서비스 제공)']` | ['law enforcement agencies'] · ['관계사', '업무수탁자'] · None · None · ['관계사', '업무수탁자'] |
| `data_usage.third_party_purposes` | `['수사', '본인확인', '서비스 위탁', '요금정산', '통계/연구']` | ['investigative'] · ['원활한 서비스 제공', '회원 편의 증진'] · None · None · ['원활한 서비스 제공', '회원 편의 증진'] |
| `liability.compensation_description` | `'회사 귀책 서비스 중단 시 이용기간 무료 연장 (24시간 초과 시 초과분의 2배 추가)'` | '사업자의 책임 있는 사유로 인한 서비스 중지 또는 장 · '서비스 중지•장애시간만큼 무료로 서비스 이용기간 연장 · '천재지변 또는 이에 준하는 불가항력, 회원의 아이디  · '책임 있는 사유로 인한 서비스 중지 또는 장애의 경우 · '서비스 중지·장애시간만큼 무료로 서비스 이용기간 연장 |
| `unfair_clause_flags` | `['POST-01', 'POST-04', 'POST-05', '면책/손배 제한', '약관 일방 변경권', '의사표시_의제']` | ['면책_손배_제한'] · ['면책_손배_제한'] · [] · [] · ['간접손해 제외', '광고 책임 없음', '데이터 통 |
