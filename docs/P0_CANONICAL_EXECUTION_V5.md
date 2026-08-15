# P0 Canonical Execution v5 Migration

## 목적

v5는 한 거래의 **피처 시각**, **의사결정/진입 시각**, **실행 후 가격 경로**를 분리한다. 1시간 신호 계산은 유지하되, 페이퍼 거래의 TP·SL·trailing 평가는 실제 `entry_ts` 이후의 완성 5분 OHLC를 사용한다. 이 문서는 `canonical_execution_plan_v2_5m` 이후의 운영·분석 계약을 정의한다.

> v5 이전의 v3/v4 성과는 historical/legacy 연구용이다. v5 trade outcome, P&L, calibration, fire-rights 분석과 절대 혼합하지 않는다.

## 데이터 계약

| 필드 | 의미 | 불변성 |
|---|---|---|
| `feature_bar_ts` | 신호 피처가 참조한 최신 1H 봉의 시각 | 기록 후 변경 금지 |
| `decision_ts` | 엔진이 페이퍼 진입을 승인한 실제 UTC 시각 | 기록 후 변경 금지 |
| `entry_ts` | 페이퍼 entry 가격의 기준 시각 | `decision_ts`와 동일 |
| `execution_plan.entry/TP/SL` | decision-price 기준 절대 가격 barrier | 기록 후 변경 금지 |
| `execution_path` | `entry_ts` 이후 5분 완성 OHLC의 entry 대비 상대 경로 | 증분 추가만 허용 |
| `path_bar_minutes` | execution replay 해상도 | v5는 `5` |
| `t_max` | 시간 단위 보유상한 | 언제나 시간(hour); evaluator가 5분 봉 수로 변환 |

`snapshot_id`는 feature bar 기준으로 유지된다. 재실행이 같은 feature bar를 중복 기록하지 않으면서도, execution plan과 ledger에는 실제 decision time이 보존된다.

## 운영 흐름

1. 매시 :05 signal workflow가 1H 피처와 현재 paper entry price를 생성한다.
2. 엔진은 `decision_ts`와 `feature_bar_ts`를 분리해 v5 execution plan을 고정한다.
3. Signal/score workflow는 OKX 5분 OHLC를 별도로 수집하며, 형성 중인 마지막 5분 봉은 절대 평가하지 않는다.
4. score workflow는 candidate별 `execution_path`를 `entry_ts`의 5분 봉부터 증분 캡처한다.
5. Notion OPEN signal과 offline `labels.py`는 같은 plan 및 5분 path를 사용한다.
6. `ENGINE_APPROVED → LEDGER_CREATED/SUPPRESSED_OPEN/LEDGER_WRITE_FAILED → CLOSED` 이벤트는 `data/decision_ledger`에 append-only로 남고 workflow가 research data와 함께 push한다.

## 안전 데이터 계약

`data_pipeline.collect()`은 `microstructure['liquidation']`을 top-level `liquidations`로 전달한다. 이 객체는 WRF LIQ_CASCADE veto와 analysis engine이 사용하는 단일 raw source다.

기본값 `WRF_VETO_REQUIRE_LIQ_DATA=true`에서 liquidation API가 unavailable이면 `LIQ_DATA_UNAVAILABLE` global veto가 생성된다. 이는 “청산이 없었다”가 아니라 “청산 안전 조건을 확인할 수 없었다”는 의미다. 연구 재생에서만 명시적으로 비활성화할 수 있으며, 페이퍼 운용에서는 활성 상태를 유지한다.

## 공통 gate 계약

`wrf.gates`가 다음을 단일 계산한다.

| 단계 | 함수 | 산출물 |
|---|---|---|
| BO 실행기하 조정 | `execution_probability()` | prior/cal 실행확률과 `p_execution_adjustment` |
| 발사 판정 | `gate_decision()` | EV/RR, floor, quarantine, veto, fire |
| 저장 후보 재생 | `replay_gate()` | production 동일 fire 판정 |

`p_execution_adjustment`는 v5 candidate에 영구 저장된다. 따라서 offline audit은 detector 전용 box geometry를 역추론하지 않아도 실제 gate를 재생할 수 있다.

## 분석 정책

v5 candidate는 `execution_path`가 비어 있으면 `tb_outcome`이 null이다. 1H snapshot path로 폴백하면 decision time부터 첫 시간봉 종료까지의 barrier touch를 다시 누락시키므로 금지한다.

`diagnose_fp_fn.py`는 shared `replay_gate()`를 사용한다. legacy rows에 adjustment가 없으면 값 0으로만 재생되며, 보고서에서는 legacy로 별도 표기해야 한다.

## 배포 후 수용 절차

| 기간 | 확인 항목 | 수용 조건 |
|---|---|---|
| 첫 signal run | v5 snapshot schema와 `feature_bar_ts`/`decision_ts` | 두 시각이 모두 존재하고 합리적 순서를 가짐 |
| 첫 approved trade | plan 및 ledger persistence | `ENGINE_APPROVED`와 terminal state가 repository ledger에서 재조회됨 |
| 첫 15분 score run | entry 직후 5분 path | `execution_path.start_bar_ts`가 entry 5분 구간과 일치 |
| 첫 closed trade | live/offline parity | Signal Log status·exit price·R과 labels 결과가 일치 |
| 2주 shadow | coverage/availability | `LIQ_DATA_UNAVAILABLE`, ledger mismatch, path expiry를 일별 대사 |

## 롤백

기존 v3/v4 연구 파일은 변경하지 않는다. 코드 rollback이 필요하면 commit을 되돌리되, 이미 생성된 v5 rows는 별도 execution semantics로 유지해야 한다. `WRF_VETO_REQUIRE_LIQ_DATA=false`는 일시적 연구 재생에만 사용하며 운영 기본값을 바꾸는 롤백 수단으로 사용하지 않는다.
