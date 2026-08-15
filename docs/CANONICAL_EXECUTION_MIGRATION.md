# Canonical Execution Plan Migration (Schema v4)

## 목적

Schema v4부터 sig-bot-1H의 한 거래는 **엔진 후보, 페이퍼 Signal Log, decision ledger, 오프라인 라벨**에서 동일한 `execution_plan`으로 정의된다. 이 문서는 v3의 사후 기준가 재배치와 상태 누락을 중단하고, 새 데이터가 재현 가능한 거래 단위가 되도록 하는 운영 계약이다.

> **불변식:** 의사결정 시점에 확정한 절대 `entry`, `TP`, `SL`, `trail_dist`, `t_max`는 어떤 소비자도 다음 봉 시가·현재가·다른 기준가로 재계산하지 않는다.

## 새 실행계획 계약

`src/wrf/execution.py`가 모든 plan의 생성과 평가를 담당한다. 엔진은 후보를 승인할 때 아래를 `execution_plan`으로 동결하고, `schema.py`는 이를 JSONL에 손실 없이 기록한다.

| 필드 | 의미 | 변경 가능 여부 |
|---|---|---|
| `decision_id` | plan·Signal Log·상태 이벤트를 연결하는 안정 ID | 불변 |
| `decision_ts` / `symbol` / `setup` / `dir` | 결정 문맥 | 불변 |
| `price_basis` | 현재 `decision_price` | 불변 |
| `entry` / `tp` / `sl` / `r_dist` / `rr` | 절대 가격 실행 규칙 | 불변 |
| `trail_dist` | 절대 trailing 거리 또는 `null` | 불변 |
| `t_max` | 보유 한도(시간봉 수) | 불변 |
| `same_bar_policy` | 고정 TP/SL 동시 터치 시 `SL_FIRST` | 불변 |
| `trailing_bar_policy` | 1H OHLC에서는 `PRIOR_STOP_ONLY` | 불변 |
| `config_hash` / `code_sha` | 당시 실행 구성·코드 식별자 | 불변 |

## 단일 평가기

`execution.evaluate_plan(plan, absolute_future_ohlc)`가 유일한 청산 평가기다.

* **Notion Signal Log:** `notion_wrf._eval_canonical_signal()`이 동일 평가기를 호출한다.
* **오프라인 라벨:** `labels._canonical_tb()`가 상대 JSONL path를 `p0`으로 절대 OHLC로 복원한 뒤 동일 평가기를 호출한다.
* **Trailing:** 1H OHLC는 high와 low의 시간 순서를 제공하지 않는다. 그러므로 현재 봉에서는 전 봉에서 확정된 stop만 사용하고, HWM/stop 갱신은 봉 종료 후 다음 봉부터 적용한다.

v4 데이터에서는 다음 봉 시가를 진입가로 삼아 TP/SL을 비례 이동시키는 legacy triple-barrier rebasing을 사용하면 안 된다.

## 상태 원장

`src/wrf/logger.py`는 `data/decision_ledger/{SYMBOL}/{YYYY-MM}.jsonl`에 append-only 이벤트를 기록한다. 각 `(decision_id, state)`는 멱등이다.

```text
ENGINE_APPROVED
  -> SUPPRESSED_OPEN      (원장 OPEN 존재, 같은 실행 중복, 또는 원장 불명)
  -> LEDGER_CREATED       (Signal Log 기록 성공)
  -> LEDGER_WRITE_FAILED  (Signal Log 기록 실패)
LEDGER_CREATED
  -> CLOSED               (청산 평가 및 Notion PATCH 성공)
```

Notion OPEN 조회가 비활성·권한 오류·네트워크 오류로 불명(`None`)이면 `main.py`는 **fail-closed**로 `SUPPRESSED_OPEN: ledger_unavailable`을 기록한다. 기존의 fail-open 방식은 엔진 `fire=True`만 남고 Signal Log가 없는 거래를 만들 수 있으므로 금지한다.

## 확률 및 EV 계약

모델 확률과 발사 확률은 다르다.

| 필드 | 의미 |
|---|---|
| `p_prior` / `p_cal` | 모델 prior와 보정 모델 확률 |
| `p_execution_prior` / `p_execution_cal` | BO near-SL 등 실행기하 보정을 동일 적용한 확률 |
| `p_execution` / `p_hat` | 실제 발사에 사용한 확률 |

`analysis/backtest.py`의 v4 A/B Brier 비교는 `p_execution_prior`와 `p_execution_cal`만 사용한다. 또한 EV/RR gate는 `p_source`가 `prior`인지 `calibrated`인지와 관계없이 항상 적용된다.

## v3 데이터 처리

기존 schema v3 JSONL은 `execution_plan`이 없어 당시의 절대 거래 규칙을 완전히 복원할 수 없다. 따라서 v3은 **`legacy_v3` 연구 데이터**로만 취급한다.

1. 기존 JSONL을 수정하거나 v4로 재라벨하지 않는다.
2. `analysis/backtest.py`는 v4 표본이 생기면 legacy v3을 자동 제외한다.
3. v4가 아직 없으면 결과에 `legacy v3 연구용` 경고를 표시하며, 실거래 근사 성과로 해석하지 않는다.
4. canonical v4 표본만으로 새 OOS·보정·레짐 분석을 다시 시작한다.

## 운영 전 체크리스트

| 검증 | 명령 또는 증적 | 통과 조건 |
|---|---|---|
| 정적 검사 | `python3 -m py_compile ...` | 오류 없음 |
| 계약 테스트 | `python3 -m unittest discover -s tests -v` | 전체 PASS |
| 스키마 | 새 JSONL 후보 | `execution_plan`, `decision_id`, `trail_dist`, `config_hash`, `code_sha` 존재 |
| 원장 | 새 approved plan | `ENGINE_APPROVED` 이후 최종 상태 정확히 하나 |
| ledger 대사 | Signal Log와 decision ledger | `decision_id` 기준 100% join |
| 평가 parity | Signal Log close vs labeler | outcome·exit price·R 완전 일치 |

## 배포 순서

1. 이 변경을 배포한 뒤 생성되는 JSONL만 canonical v4로 분류한다.
2. 첫 2주 동안은 decision ledger와 Signal Log의 `decision_id` 대사를 매 실행 확인한다.
3. trailing을 활성화하기 전에는 최소 한 개의 TF v4 plan에서 `trail_dist`·`CLOSED` event·offline label을 end-to-end로 확인한다.
4. 그 후에만 backtest의 canonical v4 성과를 과적합·비용·레짐 분석의 입력으로 사용한다.

이 문서는 전략의 수익성을 보장하지 않는다. 목표는 성과를 측정하기 전에 **거래 정의를 하나로 만드는 것**이다.
