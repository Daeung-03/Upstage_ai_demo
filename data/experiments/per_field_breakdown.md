# Per-field × Per-fixture Error Breakdown

**Source**: 15 fixtures × 5 최근 raw runs (R9 측정) — total ≈ 75 measurements 의
fixture × field × category 매트릭스. diagnose_golden_vs_model.py 의 6 카테고리
분류 (A/B/C/D/E/X) 재사용. alias normalization 적용 (`_ENUM_ALIAS_GROUPS`).

## 🔴 Top 20 fields by **D** (모델 추출 실패 — 가장 많은 fixture 에서 모델 5/5 not_specified)

| Rank | Field | D 카운트 (fixture 수) |
|---|---|---|
| 1 | `cancellation.third_party_cancellation_required` | **15** |
| 2 | `account.sharing_restrictions` | **15** |
| 3 | `service.availability_disclaimer` | **15** |
| 4 | `account.minimum_age` | **14** |
| 5 | `terms_changes.price_change_explicit_consent` | **12** |
| 6 | `service.regional_content_restriction` | **12** |
| 7 | `cancellation.cooling_off_refund_days` | **11** |
| 8 | `cancellation.cooling_off_conditions` | **11** |
| 9 | `pricing.price_change_notice_channels` | **6** |
| 10 | `cancellation.notice_period_days` | **6** |
| 11 | `pricing.billing_cycle` | **4** |
| 12 | `pricing.price_change_notice_days` | **4** |
| 13 | `cancellation.penalty_present` | **3** |
| 14 | `data_usage.marketing_use` | **3** |
| 15 | `liability.force_majeure_scope` | **3** |
| 16 | `disputes.arbitration_required` | **3** |
| 17 | `disputes.class_action_waiver` | **3** |
| 18 | `pricing.auto_renewal_enabled` | **2** |
| 19 | `free_trial.auto_convert_to_paid` | **2** |
| 20 | `free_trial.cancel_required_before_end` | **2** |

## ⚠️ Top 20 fields by **B** (consensus disagrees with golden — 모델 부정확 또는 golden 의심)

| Rank | Field | B 카운트 |
|---|---|---|
| 1 | `disputes.jurisdiction_clause` | **8** |
| 2 | `unfair_clause_flags` | **7** |
| 3 | `terms_changes.notice_channels` | **6** |
| 4 | `cancellation.notice_period_days` | **5** |
| 5 | `disputes.governing_law` | **5** |
| 6 | `cancellation.method` | **4** |
| 7 | `data_usage.third_party_sharing` | **4** |
| 8 | `free_trial.payment_method_required_upfront` | **3** |
| 9 | `data_usage.marketing_use` | **3** |
| 10 | `liability.service_disruption_compensation` | **3** |
| 11 | `pricing.auto_renewal_consent` | **2** |
| 12 | `terms_changes.notice_lead_time_days` | **2** |
| 13 | `terms_changes.user_consent_mechanism` | **2** |
| 14 | `terms_changes.silent_acceptance_clause` | **2** |
| 15 | `data_usage.cross_border_transfer` | **2** |
| 16 | `liability.compensation_description` | **2** |
| 17 | `liability.force_majeure_scope` | **2** |
| 18 | `disputes.arbitration_required` | **2** |
| 19 | `pricing.billing_cycle` | **1** |
| 20 | `cancellation.method_description` | **1** |

## ➕ Top 10 fields by **E** (over-extraction — golden null, 모델 일관 invent)

| Rank | Field | E 카운트 |
|---|---|---|
| 1 | `cancellation.penalty_description` | **2** |
| 2 | `data_usage.collected_categories` | **2** |
| 3 | `data_usage.third_party_recipients` | **2** |
| 4 | `data_usage.third_party_purposes` | **2** |
| 5 | `data_usage.marketing_use` | **2** |
| 6 | `pricing.billing_cycle` | **1** |
| 7 | `pricing.auto_renewal_enabled` | **1** |
| 8 | `pricing.auto_renewal_consent` | **1** |
| 9 | `pricing.price_change_notice_days` | **1** |
| 10 | `pricing.price_change_notice_channels` | **1** |

## Per-fixture summary

| Fixture | A | B | C | D | E | total |
|---|---|---|---|---|---|---|
| netflix | 30 | 2 | 3 | **13** | 0 | 51 |
| spotify | 25 | 7 | 6 | **10** | 0 | 51 |
| wavve | 28 | 4 | 5 | **11** | 3 | 51 |
| coupang_play | 18 | 3 | 7 | **15** | 0 | 51 |
| tving | 23 | 11 | 6 | **10** | 1 | 51 |
| disney_plus | 24 | 5 | 7 | **11** | 0 | 51 |
| watcha | 22 | 2 | 8 | **13** | 2 | 51 |
| claude | 24 | 9 | 4 | **10** | 2 | 51 |
| deepseek | 25 | 3 | 3 | **9** | 3 | 51 |
| gemini | 15 | 2 | 10 | **18** | 0 | 51 |
| gpt | 22 | 6 | 8 | **8** | 7 | 51 |
| upstage | 15 | 10 | 12 | **8** | 6 | 51 |
| banksalad | 27 | 3 | 5 | **12** | 0 | 51 |
| kakaopay | 33 | 2 | 2 | **7** | 0 | 51 |
| toss | 33 | 2 | 1 | **11** | 0 | 51 |

## 행동 권장

- **D 상위 필드** (모델이 *반복적으로* 추출 못 하는 필드) 에 prompt 룰 추가 후보.
  - 도메인별 default 값 inferred 룰 (예: 한국 OTT 의 `auto_renewal_enabled=True` default).
  - 자유텍스트 단축 방지 (penalty_description, force_majeure_scope 같이).
- **B 상위 필드** 는 case-by-case. golden 본문 audit + 모델 출력 비교 → 라벨 fix or     prompt 룰 추가.
- **E 상위 필드** 는 모델의 over-inference. 'inferred False' 룰을 *너무 적극적으로*     적용하는 경우.
