# sig-bot-1H — WRF-4 Canonical Execution v5

OKX USDT 무기한 선물 시장을 대상으로 하는 **1시간 신호·페이퍼 트레이딩 연구 시스템**입니다. 이 저장소는 실주문을 제출하지 않습니다. v5의 핵심 목표는 알파 신호를 더 공격적으로 바꾸는 것이 아니라, **한 거래가 엔진·Signal Log·상태 원장·오프라인 라벨에서 정확히 같은 의미를 갖도록 만드는 것**입니다.

> **운영 상태:** 페이퍼 전용이며, 신규 v5 표본 축적 및 shadow 검증 단계입니다. 기존 v3/v4 성과와 v5 성과를 합산해 전략 성과나 알파를 판단하면 안 됩니다.

> **면책:** 본 프로젝트는 연구·교육·페이퍼 관측용입니다. 투자 판단, 주문 실행 및 손실 책임은 사용자에게 있습니다.

---

## 목차

- [시스템 목적과 경계](#purpose)
- [v5의 핵심 변화](#v5-changes)
- [알고리즘 논리 구조](#architecture)
- [한 거래의 canonical 정의](#canonical-trade)
- [신호 생성과 발사 판단](#signal-and-gating)
- [실행·청산·라벨 재생](#execution-and-labeling)
- [안전 데이터와 상태 원장](#safety-and-ledger)
- [v4 대비 상세 비교](#v4-v5-comparison)
- [데이터 스키마와 버전 경계](#schema)
- [운영 워크플로우](#operations)
- [검증과 테스트](#testing)
- [프로젝트 구조](#structure)
- [제약과 다음 관측 게이트](#limitations)

---

<a id="purpose"></a>
## 시스템 목적과 경계

WRF는 **Win-Rate-First**의 약자로, 다수의 저품질 신호를 내기보다 구조·위치·흐름이 함께 정렬된 후보만 기록하고, 보수적 확률·기대값·안전 제약을 모두 통과한 후보만 페이퍼 Signal Log에 생성합니다. 시스템은 다음 네 계층을 분명히 구분합니다.

| 계층 | 역할 | v5에서의 원칙 |
|---|---|---|
| 신호 연구 | 1H 시장 구조, 레짐, C/L/F 축으로 후보 생성 | 알파 로직은 v4의 검증된 구조를 유지 |
| 실행 정의 | entry·TP·SL·trailing·time stop을 하나의 plan으로 고정 | 승인 뒤 가격 장벽을 재계산하지 않음 |
| 페이퍼 원장 | Signal Log와 `decision_ledger`에 상태를 남김 | 외부 원장 실패는 새 포지션 생성으로 이어지지 않음 |
| 오프라인 검증 | 미래 OHLC 경로로 같은 plan을 재생 | live와 다른 진입 시점·TP/SL·gate를 사용하지 않음 |

현재 시스템은 **실주문, 레버리지 주문 관리, 실제 체결·슬리피지 모델링, 포지션 자본 배분**을 수행하지 않습니다. 따라서 페이퍼 성과가 곧 실거래 성과라는 의미는 아닙니다.

---

<a id="v5-changes"></a>
## v5의 핵심 변화

v5는 단일 변경이 아니라, 이전에 서로 달랐던 거래 정의를 하나로 고정하는 **execution semantics 개편**입니다. 신호를 만드는 TF·BO·MR·RV 디텍터의 경제적 가설 자체를 재최적화하지 않았습니다. 대신 신호가 승인된 후 어떤 가격·어떤 시각·어떤 경로로 승패를 판정하는지를 통일했습니다.

| 영역 | v4 이전 문제 | v5 변경 | 기대 효과 |
|---|---|---|---|
| 시간축 | 1H feature 봉 시각, 실제 :05 decision 시각, 다음 1H 봉 재생 시각이 혼재 | `feature_bar_ts`, `decision_ts`, `entry_ts`를 분리 | 신호 시점과 평가 시점의 혼동 제거 |
| 거래 장벽 | offline path가 나중 봉 시가에 맞춰 TP/SL을 사실상 재기준화할 수 있었음 | 절대 `entry/TP/SL/trail_dist/t_max`를 immutable plan에 고정 | live·offline 장벽 동일화 |
| 가격 경로 | 진입 직후 현재 1H 봉의 일부 구간을 놓칠 수 있었음 | `entry_ts`부터 **완성 5분 OHLC**를 후보별로 증분 저장 | :05~다음 1H 봉 마감 사이의 TP/SL touch 보존 |
| trailing | 같은 OHLC 봉에서 고점→저점 순서를 낙관적으로 가정할 여지 | 이전 봉의 stop만 현재 봉에 적용하는 `PRIOR_STOP_ONLY` | 알 수 없는 intrabar 순서에 대한 낙관 편향 차단 |
| 안전 veto | microstructure의 liquidation 데이터가 veto 입력까지 전달되지 않음 | 단일 `liquidations` 계약으로 배선, 미가용은 명시적 veto | API 실패를 “청산 없음”으로 오인하지 않음 |
| 발사 판단 | BO 실행기하 보정·EV·floor·격리 로직을 소비자가 별도 근사 가능 | `wrf.gates` 공통 함수로 engine과 audit을 통합 | FP/FN 진단과 production gate의 의미 일치 |
| 상태 관리 | Notion 장애 또는 workflow persistence 누락 시 이벤트 회계 누수 가능 | append-only `decision_ledger`와 workflow commit 범위 확장 | 승인·억제·원장 생성·종료 추적성 확보 |

> v5의 변화는 “더 좋은 신호를 찾았다”는 주장이 아닙니다. **성과 측정과 위험 통제의 의미론을 수리한 것**입니다. 새로운 v5 표본이 충분히 쌓이기 전에는 성능 개선을 주장할 수 없습니다.

---

<a id="architecture"></a>
## 알고리즘 논리 구조

```text
OKX read-only data
  └─ 1H / 4H / 1D market data + ticker + microstructure
       └─ L0: global safety veto
       └─ L1: features, percentile, regime, BTC macro, context
       └─ L2: TF / BO / MR / RV detector → C/L/F candidate
       └─ L3: prior / calibration probability evaluation
       └─ L4: absolute levels + canonical gate + immutable execution plan
              ├─ JSONL v5 research snapshot
              ├─ decision ledger state event
              ├─ Notion paper Signal Log
              └─ 5m execution-path capture and common plan replay
```

### L0 — 전역 안전 veto

L0는 알파가 아니라 **운영 안전성**을 담당합니다. 전역 veto가 존재하면 후보의 확률이 높아도 발사되지 않습니다.

| veto | 의미 | v5 처리 |
|---|---|---|
| `DATA_STALE` | 신호 입력의 시간 신선도가 기준을 넘음 | 발사 차단 |
| `LIQ_DATA_UNAVAILABLE` | 청산 데이터 수집 상태를 검증할 수 없음 | 기본 fail-closed 발사 차단 |
| `LIQ_CASCADE` | 진입 방향에 불리한 대규모 청산 cascade | 발사 차단 |
| spread / macro veto | 비정상 호가 또는 거시 정면충돌 | 발사 차단 |

`WRF_VETO_REQUIRE_LIQ_DATA=true`가 기본값입니다. 연구 재생에서만 명시적으로 조정할 수 있으며, 페이퍼 운용에서 data-feed 장애를 0건 청산으로 해석해서는 안 됩니다.

### L1 — 피처·레짐·맥락

L1은 시장 상태를 숫자와 범주로 표현합니다. 1H 레짐은 허용 셋업을 라우팅하고, BTC 거시·일봉 바이어스·4H 구조는 C축 또는 veto의 입력이 됩니다. 절대 임계값보다 심볼 자기분포 백분위를 우선 사용해 자산별 변동성 스케일 차이를 완화합니다.

| 구성 | 예시 | 사용 위치 |
|---|---|---|
| 시장 레짐 | TRENDING, EXPLOSIVE, SQUEEZE, RANGING | 허용 셋업·calibration cell |
| BTC 거시 | UPLEG, DOWNLEG, CHOP | C축·macro veto·cell |
| 위치 | VWAP/EMA/BB/ATR 정규화 거리 | L축 |
| 흐름 | RSI·MACD·테이커·OI·펀딩·청산 | F축 및 safety input |

v5의 중요 변화는 L1의 알파 식이 아니라 **시간 메타데이터**입니다. 피처가 계산된 1H 봉 시각은 `feature_bar_ts`, 그 피처를 읽고 페이퍼 entry를 승인한 실제 UTC 시각은 `decision_ts`로 별도 보존됩니다.

### L2 — 4개 셋업과 C/L/F 후보

| 셋업 | 가설 | 대표 구조 조건 | levels 개념 |
|---|---|---|---|
| `TF` | 추세 내 pullback 재개 | 4H 정렬, 1H/4H pullback, 모멘텀·구조 확인 | swing·ATR 기반 SL, target 또는 trailing |
| `BO` | 박스 경계 돌파의 지속 | 종가 돌파, 거래량 spike, retest 유지 | box-height target, near-boundary SL |
| `MR` | range의 과도한 이탈 회귀 | BB·RSI 극단, 반전 candle/volume | 중심선 또는 반대 경계 target |
| `RV` | 구조 전환 | 소진, 반전 candle, 확인 조건 | 이전 level target, extreme 외부 SL |

모든 후보는 방향별로 생성되고, **C(맥락), L(위치), F(흐름)** 축을 함께 기록합니다. 이 축은 확률 prior와 calibration 입력이며, 장벽 자체를 사후적으로 바꾸지 않습니다.

### L3 — 확률 prior와 calibration

엔진은 candidate의 C/L/F·셋업·레짐·거시 cell을 사용해 prior 및 calibration 확률을 평가합니다. calibration은 표본 부족 cell에서 부모 집단으로 수축되는 부분풀링 구조이며, 운영 기본값에서 prior와 calibration의 관계는 설정에 의해 제어됩니다.

v5는 BO의 SL-tightness와 같은 **실행기하 조정값**을 `p_execution_adjustment`로 명시 저장합니다. 따라서 다음 두 질문을 분리할 수 있습니다.

1. 모델이 구조상 이 후보를 얼마나 좋게 평가했는가 (`p_prior`, `p_cal`)?
2. 실제 entry·SL geometry를 고려한 뒤의 발사 확률은 얼마인가 (`p_execution`)?

### L4 — canonical gate와 페이퍼 발사

v5의 발사 판정은 공통 모듈 `wrf.gates`가 계산합니다.

```text
fire = (p_execution ≥ floor)
       AND (global/candidate veto 없음)
       AND (EV/RR 안전 조건 통과)
       AND (shadow setup 또는 fire-rights 격리 아님)
```

EV gate가 활성화된 경우 다음을 모두 확인합니다.

```text
EV = p_execution × RR − (1 − p_execution)
EV ≥ WRF_EV_MIN
RR ≥ WRF_EV_RR_FLOOR
```

여기서 calibration은 확률을 바꿀 수는 있어도, **음의 EV 거래를 통과시키는 권한은 없습니다**. 같은 실행에서 동일 방향 후보가 여러 개 생기면 가장 높은 실행 확률 후보만 남기며, 외부 Signal Log의 OPEN 상태가 불명확하면 새 포지션 생성은 fail-closed로 억제됩니다.

---

<a id="canonical-trade"></a>
## 한 거래의 canonical 정의

v5에서는 승인된 거래를 아래 execution plan 하나로 정의합니다. plan은 승인 뒤 변경하지 않으며, 모든 소비자(engine, ledger, Notion, labels, audit)가 이 값을 사용해야 합니다.

| 필드 | 정의 | 소비자 |
|---|---|---|
| `decision_id` | plan·config hash·code identity를 반영한 안정적 식별자 | 상태 원장·대사 |
| `feature_bar_ts` | 최신 1H 피처 봉의 시각 | 신호 재현·snapshot identity |
| `decision_ts` | 엔진 승인 시각 | entry path의 시작 기준 |
| `entry_ts` | 페이퍼 entry 시각; 현재 `decision_ts`와 동일 | 5m path capture |
| `entry`, `tp`, `sl` | decision-price 기준의 절대 barrier | live/offline 공통 평가 |
| `r_dist`, `rr`, `t_max` | 리스크 거리·보상비·시간 상한 | EV와 timeout 평가 |
| `trail_dist` | trailing 활성 시 절대 거리 | 공통 evaluator |
| `path_timeframe`, `path_bar_minutes` | execution path 해상도 | v5는 `5m`, `5` |
| `same_bar_policy` | TP/SL이 같은 봉에 닿는 경우의 순서 | 기본 `SL_FIRST` |
| `trailing_bar_policy` | trailing stop의 intrabar 처리 | 기본 `PRIOR_STOP_ONLY` |

### v5 시간축

```text
feature_bar_ts ──► 1H 피처가 확정된 데이터 기준
                      │
                      ▼
decision_ts = entry_ts ──► 엔진 승인·페이퍼 entry
                              │
                              ▼
                  완성 5분 OHLC 경로를 entry 구간부터 증분 저장
                              │
                              ▼
             동일 plan으로 Signal Log 종료와 offline triple-barrier 재생
```

이 설계는 신호가 :05에 발생했는데 offline 평가가 다음 정시 1H 봉부터 시작되는 문제를 해결합니다. 현재 진행 중인 5분 봉은 평가하지 않으며, 마지막 **완성된** 5분 봉까지만 사용합니다.

---

<a id="execution-and-labeling"></a>
## 실행·청산·라벨 재생

### 절대 barrier와 보수적 OHLC 정책

fixed TP/SL은 plan의 절대 가격을 그대로 사용합니다. 한 OHLC 봉에서 TP와 SL이 모두 닿으면 `SL_FIRST`로 처리합니다. 이는 실제 intrabar 순서를 알 수 없는 1H/5m OHLC 자료에서 수익 쪽 순서를 임의로 가정하지 않기 위한 보수적 정책입니다.

trailing plan은 현재 봉의 고점으로 stop을 즉시 올린 뒤 같은 봉의 저점으로 hit를 판정하지 않습니다. 먼저 **이전 봉까지 확정된 stop**으로 현재 봉을 평가하고, 그 뒤 현재 봉의 고점/저점으로 다음 봉용 stop을 업데이트합니다. 이것이 `PRIOR_STOP_ONLY`입니다.

### candidate별 `execution_path`

v5 snapshot의 각 candidate는 `entry_ts` 이후 5분 OHLC를 `execution_path`로 별도 축적합니다. `t_max`는 여전히 시간(hour) 단위이고 evaluator가 5분 봉 수로 환산합니다. 예를 들어 `t_max=24`는 최대 288개 완성 5분 봉을 평가합니다.

v5 candidate에 5분 path가 없으면 `tb_outcome`은 null로 남습니다. 이때 기존 1H `path`로 폴백하는 것은 금지됩니다. 그러한 폴백은 v5가 제거하려는 entry-time gap을 다시 도입하기 때문입니다.

---

<a id="safety-and-ledger"></a>
## 안전 데이터와 상태 원장

### 단일 청산 데이터 계약

`microstructure['liquidation']`은 `data_pipeline.collect()`에서 top-level `liquidations`로 전달됩니다. 같은 raw object를 analysis engine과 WRF `LIQ_CASCADE` veto가 공유합니다. 이 배선으로 수집층에서 존재하던 청산 데이터가 발사 안전 제약까지 실제로 전달됩니다.

### Append-only decision ledger

Notion은 사용자 인터페이스와 페이퍼 Signal Log로 유용하지만, 외부 API 상태만으로 거래 상태를 정의하지 않습니다. v5는 `data/decision_ledger/{symbol}/{YYYY-MM}.jsonl`에 다음 상태 전이를 append-only로 기록합니다.

```text
ENGINE_APPROVED
  ├─ LEDGER_CREATED
  ├─ SUPPRESSED_OPEN
  └─ LEDGER_WRITE_FAILED
        └─ CLOSED  (원본 immutable plan을 찾아 종료 이벤트 기록)
```

Signal 및 scoring GitHub Actions workflow는 `data/research`뿐 아니라 `data/decision_ledger`도 함께 commit합니다. Notion의 OPEN 상태를 조회할 수 없으면 새 신호를 만들지 않는 fail-closed 경로를 사용합니다.

---

<a id="v4-v5-comparison"></a>
## v4 대비 상세 비교

### 무엇이 유지되었는가

v5는 다음 신호 가설을 변경하거나 성능이 좋아졌다고 주장하지 않습니다.

| 유지 항목 | 설명 |
|---|---|
| 4 setup universe | TF·BO·MR·RV 후보의 경제적 가설과 기본 detector 구조 |
| C/L/F 표현 | context·location·flow의 직교 입력과 prior/calibration 활용 |
| regime routing | 1H/4H 레짐에 따른 허용 setup 라우팅 |
| probability discipline | prior, calibration, fire-rights, shadow setup의 역할 분리 |
| paper-only boundary | 실주문 부재 및 alert/Notion 기반 관측 운영 |

### 무엇이 달라졌는가

| 질문 | v4 또는 legacy 경로 | v5 canonical 경로 |
|---|---|---|
| “신호는 언제 발생했는가?” | 1H 봉 timestamp가 decision 시각처럼 사용될 수 있음 | `feature_bar_ts`와 `decision_ts`를 별도 기록 |
| “entry는 어느 가격인가?” | 기록 가격과 offline 다음 봉 기준이 달라질 수 있음 | immutable plan의 decision-price entry 하나 |
| “TP/SL은 어디인가?” | 후속 봉에 맞춘 재계산·rebase 위험 | plan의 절대 가격 그대로 |
| “첫 손절/익절 기회는?” | 현재 1H 봉 잔여 구간이 누락될 수 있음 | decision 구간부터 5m 완성 OHLC로 저장 |
| “같은 봉 양쪽 barrier hit는?” | 구현 경로별 가정 차이 가능 | 공통 `SL_FIRST` |
| “trailing은 어떻게 재생되는가?” | 동봉 고점 후 저점을 가정할 위험 | `PRIOR_STOP_ONLY` |
| “청산 feed 실패는?” | 빈 dict가 0건 청산처럼 전달될 수 있음 | `LIQ_DATA_UNAVAILABLE` veto |
| “audit은 engine을 재현하는가?” | BO adjustment·EV/floor의 근사 재계산 가능 | shared `gates.replay_gate()` 사용 |
| “Notion 실패 시 거래 상태는?” | JSONL/Notion 상태의 분리 위험 | immutable plan 기반 decision ledger 우선 |

### 성과 해석에 미치는 영향

v5가 v4 성과를 소급 보정하는 것이 아닙니다. v5는 더 세밀한 entry path를 사용하므로 일부 historical outcome이 달라질 수 있고, 그것은 “전략이 변했다”기보다 과거 평가가 execution semantics에 의존했음을 의미합니다. 따라서 다음 원칙을 준수합니다.

1. `legacy_v3`, v4, `canonical_execution_plan_v2_5m`은 별도 cohort로 집계합니다.
2. v5의 `execution_path`가 완성되기 전에는 `tb_outcome`을 성과 표본으로 사용하지 않습니다.
3. v5가 승인·종료된 거래의 Signal Log와 JSONL labels가 `decision_id` 기준으로 일치하는지 먼저 확인합니다.
4. 충분한 v5 OOS 표본이 쌓이기 전에는 floor·prior·calibration·setup 활성화를 완화하지 않습니다.

---

<a id="schema"></a>
## 데이터 스키마와 버전 경계

연구 snapshot은 `data/research/{SYMBOL}/{YYYY-MM}.jsonl`에 저장됩니다. v5 snapshot의 `schema_version`은 5이고 execution semantics는 `canonical_execution_plan_v2_5m`입니다.

```jsonc
{
  "snapshot_id": "BTC/USDT_2026-08-15T09:00:00+00:00",
  "schema_version": 5,
  "execution_semantics": "canonical_execution_plan_v2_5m",
  "feature_bar_ts": "2026-08-15T09:00:00+00:00",
  "decision_ts": "2026-08-15T09:05:13+00:00",
  "p0": 0.0,
  "raw": { "...": "L1 feature" },
  "ctx": { "regime_1h": "...", "btc_macro": "..." },
  "candidates": [
    {
      "setup": "BO", "dir": "long",
      "p_prior": 0.0, "p_cal": 0.0,
      "p_execution": 0.0, "p_execution_adjustment": 0.0,
      "veto": [], "quarantine": [], "fire": false,
      "execution_plan": {
        "decision_id": "...", "entry_ts": "...",
        "entry": 0.0, "tp": 0.0, "sl": 0.0,
        "t_max": 36, "path_timeframe": "5m", "path_bar_minutes": 5
      },
      "execution_path": { "n": 0, "o": [], "h": [], "l": [], "c": [] }
    }
  ],
  "path": { "...": "general 1H research path" }
}
```

`path`는 일반적인 1H 연구·레짐·초과수익 분석에 사용됩니다. 후보 승패를 위한 v5 canonical barrier 재생에는 candidate의 `execution_path`만 사용합니다.

---

<a id="operations"></a>
## 운영 워크플로우

| Workflow | 스케줄 | 역할 |
|---|---|---|
| `signal_1h.yml` | 매시 :05 UTC | 수집→1H signal→v5 snapshot→decision event→Notion mirror |
| `scoring.yml` | 15분마다 | 완성 5m path 증분 저장→OPEN Signal Log 종료 평가→label backfill |
| `calibrate.yml` | 주간 | JSONL 기반 calibration table 산출; v5 cohort와 legacy cohort 분리 필요 |
| `contract_tests.yml` | push/PR | canonical execution·gate·schema·veto 회귀 차단 |

### 로컬 실행

```bash
pip install -r requirements.txt
export OKX_API_KEY=... OKX_API_SECRET=... OKX_PASSPHRASE=...
export SINGLE_SYMBOL="BTC/USDT"

python src/main.py --mode signal   # 1H 신호, v5 snapshot, paper decision
python src/main.py --mode score    # 5m execution path, OPEN 신호 판정, label backfill
python analysis/backtest.py        # cohort 경계를 확인하며 연구 성과 집계
python analysis/audit/diagnose_fp_fn.py --stride 72  # shared gate 기반 진단
```

운영 환경에서 `RESEARCH_LOGGER_ENABLED=0` 또는 `WRF_VETO_REQUIRE_LIQ_DATA=false`를 사용하면 v5 추적성과 안전 경계가 약화됩니다. 변경은 연구 목적·기간·rollback 조건을 문서화한 뒤에만 수행해야 합니다.

---

<a id="testing"></a>
## 검증과 테스트

canonical execution 회귀 계약은 `tests/test_execution_contract.py`에 있습니다.

```bash
python -m py_compile \
  src/wrf/gates.py src/wrf/execution.py src/wrf/engine.py \
  src/wrf/features.py src/wrf/logger.py src/wrf/notion_wrf.py \
  src/wrf/schema.py src/wrf/veto.py src/data_pipeline.py \
  analysis/labels.py analysis/audit/diagnose_fp_fn.py src/main.py

python -m unittest discover -s tests -v
```

현재 계약은 최소한 다음을 검증합니다.

| 계약 | 검증 의도 |
|---|---|
| absolute TP/SL | 다음 봉 시가에 맞춘 장벽 rebase 금지 |
| live/offline evaluator parity | 동일 plan과 path에서 동일 outcome |
| same-bar / trailing policy | 낙관적 intrabar ordering 금지 |
| v5 5m entry path | entry 구간과 hour-based timeout 환산 |
| schema round-trip | plan·확률 조정·식별자 보존 |
| label boundary | v5가 1H path로 폴백하지 않음 |
| common gate replay | 저장된 execution adjustment로 production gate 재현 |
| liquidation availability | feed 부재가 explicit veto가 됨 |
| decision ledger | 상태 event 멱등성 |

---

<a id="structure"></a>
## 프로젝트 구조

```text
src/
  main.py                       signal / score orchestration
  data_pipeline.py              OKX data collection and safety-data contract
  research_logger.py            1H research path + 5m execution-path capture
  wrf/
    features.py                 feature-bar / decision-time separation
    detectors.py                TF / BO / MR / RV candidate generation
    levels.py                   absolute TP / SL / time-stop geometry
    calibration.py              prior and calibration evaluation
    gates.py                    canonical execution probability and fire gate
    execution.py                immutable execution plan and common evaluator
    veto.py                     safety vetoes including liquidation availability
    schema.py                   v5 snapshot serialization
    logger.py                   research snapshot and decision ledger I/O
    notion_wrf.py               paper Signal Log integration
analysis/
  labels.py                     v5 canonical path labeling
  audit/diagnose_fp_fn.py       shared-gate false-positive/false-negative diagnostics
tests/
  test_execution_contract.py    canonical execution regression contracts
docs/
  P0_CANONICAL_EXECUTION_V5.md  detailed migration and acceptance procedure
```

---

<a id="limitations"></a>
## 제약과 다음 관측 게이트

v5는 구조적 정합성을 개선했지만, 다음 항목은 새 표본으로 운영 검증해야 합니다.

| 관측 게이트 | 확인 내용 | 통과 기준 |
|---|---|---|
| 첫 v5 approved trade | `ENGINE_APPROVED` event와 immutable plan | `decision_id` 기준 원장 재조회 가능 |
| 첫 15분 scoring cycle | `entry_ts` 직후의 5m path | `start_bar_ts`가 진입 5분 구간과 일치 |
| 첫 v5 closed trade | Notion·ledger·labels 대사 | outcome, exit price, R이 동일 |
| 2주 shadow | data coverage와 persistence | ledger mismatch·path expiry·LIQ data unavailable 일별 대사 |
| v5 cohort 성숙 | 전략 성과 평가 | legacy 분리, 독립표본·OOS·마찰 비용 포함 |

실제 체결의 수수료·스프레드·슬리피지·펀딩·부분체결은 v5 5분 OHLC paper evaluator가 완전히 모델링하지 않습니다. 그러므로 v5의 canonical outcome은 **논리적으로 일관된 페이퍼 결과**이지, 실거래 수익의 보증이나 체결 시뮬레이터가 아닙니다.

자세한 이행·운영 절차는 [`docs/P0_CANONICAL_EXECUTION_V5.md`](docs/P0_CANONICAL_EXECUTION_V5.md)를 참조하십시오.
