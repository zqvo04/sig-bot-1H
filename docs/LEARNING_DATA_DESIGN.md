# 학습 데이터 적재 로직 설계 v2 — 상태 중심(Learning-First) Research Logger

> **v1 → v2 전환 요지**: v1은 기존 신호 봇의 산출물(점수·보너스·임계값·가상 TP/SL)을 그대로 기록하는
> "신호 로직의 그림자" 설계였다. v2는 신호 로직과 분리된 **상태(state) 중심** 설계다.
> 매시간을 하나의 독립 표본으로 보고 **(시장 상태, 이후 72h 차트 경로)** 쌍을 원시 그대로 보존한다.
> "이런 상황에서 차트가 어떻게 움직였나"를 어떤 정의로든 사후에 분석할 수 있게 하는 것이 목표다.

---

## 0. 설계 원칙 (v2)

| # | 원칙 | 의미 |
|---|------|------|
| P1 | **상태 중심** | 신호 발생 여부는 표본 선정 기준이 아니라 그냥 메타데이터 1개. 매시간 = 1표본 |
| P2 | **원시 보존 (raw capture)** | 온라인(봇)에서는 가공·정규화·라벨 정의를 하지 않는다. 지표 원값과 가격 경로만 저장 |
| P3 | **라벨은 오프라인 파생** | "몇 시간 후 +X%였나", "TP/SL이면 어땠나" 등 모든 라벨은 저장된 경로에서 사후 계산. 라벨 정의를 나중에 바꿔도 재수집 불필요 |
| P4 | **경로(path) 전체 저장** | 72h 시점값만이 아니라 **시간별 close/high/low 전체 경로**를 저장 → "어떻게 움직였는지"(궤적·되돌림·페이크) 학습 가능 |
| P5 | **신호 로직 비오염** | 점수/임계값/쿨다운은 피처가 아니라 참고 메타로만. 학습 입력은 점수 이전 단계의 원시 지표 |

v1의 약점과 대응:
- v1은 `final_score`·`bonus`·가상 TP/SL 등 **신호 로직의 출력**을 피처/라벨로 썼다 → 신호 로직이 바뀔 때마다
  데이터 의미가 흔들리고, 로직의 편향이 학습 데이터에 그대로 새어 들어감. **v2는 점수 이전의 원시 지표만 피처로.**
- v1은 라벨(호라이즌·데드존·SL우선 규칙)을 **수집 시점에 고정** → 정의를 바꾸면 과거 데이터 무효.
  **v2는 경로를 저장하므로 임의의 호라이즌·임의의 TP/SL·임의의 분류 기준을 오프라인에서 무한 재정의 가능.**

---

## 1. 전체 구조 — 2단계 파이프라인 (유지)

수집 메커니즘 자체는 v1과 동일하다. 봇이 매시 1H 캔들 250개(~10일치)를 이미 수집하므로 추가 API 호출이 없다.

```
매시 실행 (main.py)
 ├─ Phase A: 상태 스냅샷 기록
 │    마감된 1H 캔들 기준의 "상태 벡터"(§2)를
 │    data/research/{SYMBOL}/{YYYY-MM}.jsonl 에 append (path=null)
 │
 └─ Phase B: 경로 캡처 (snapshot ts + 72h 경과분)
      이번 실행에서 수집된 250개 캔들로, 스냅샷 이후 72개 캔들의
      close/high/low 상대 경로(§3)를 계산해 해당 행에 기록 (path 완성)
```

- 라벨링이 아니라 **경로 캡처**라는 점이 v1과 다르다. 캡처 후에는 어떤 질문이든 오프라인에서 답한다.
- 실행 누락 내성·멱등성·상태 무의존(§5)은 v1과 동일.

---

## 2. 상태 벡터 (Phase A) — 3개 레이어

### L1. 연속 원시 피처 (학습 입력의 본체)

점수 산출 **이전** 단계(`analysis` dict)의 원값. 정규화·버킷화하지 않고 그대로 저장한다.
(정규화는 오프라인에서 — 롤링 z-score든 percentile이든 사후 선택 가능)

```jsonc
"f": {
  // 가격/변동성 (스케일 독립 표현 — 절대가 대신 비율)
  "atr_pct":…, "bb_width":…, "bb_pos":…, "bb_squeeze_h":…,    // 스퀴즈 지속시간
  "candle_body_atr":…, "candle_range_atr":…,                   // 기준 캔들 모양 (ATR 단위)
  "dist_ema20_atr":…, "dist_ema50_atr":…, "dist_ema200_atr":…, // EMA 이격 (ATR 단위)
  "ret_1h":…, "ret_4h":…, "ret_24h":…,                         // 직전 수익률 (모멘텀 원료)

  // 모멘텀/추세
  "rsi_1h":…, "rsi_4h":…, "rsi_1d":…, "rsi_1d_slope":…,
  "adx":…, "adx_slope":…, "macd_hist_atr":…, "er":…,           // 효율비
  "ema_align_1h":…, "ema_align_4h":…, "ema_align_1d":…,        // −3..+3 정수 (역/정방향 정렬 수)

  // 구조 (SMC) — 방향성 있는 것은 부호로 (+롱방향/−숏방향/0없음)
  "bos_1h":…, "choch_1h":…, "bos_4h":…, "choch_4h":…,
  "fvg":…, "order_block":…, "fib_gp":…, "weekly_lvl":…,
  "confluence_n":…, "retrace_depth":…, "maturity":…,           // 되돌림 깊이는 비율 원값
  "swing_hl":…,                                                 // higher-low/lower-high 상태

  // 심리/포지셔닝
  "funding":…, "funding_slope":…, "ls_ratio":…, "taker_ratio":…,
  "oi_chg_4h":…, "oi_slope":…, "smart_money_div":…, "liq_imbalance":…,

  // 마이크로구조
  "ob_imbalance":…, "wall_dist_atr":…, "cascade":…, "mark_prem":…,

  // 거래량/시간
  "volume_ratio":…, "hour_utc":…, "dow":…                      // 세션/요일 효과 학습용
}
```

> 표현 규칙: ① 절대가격 금지 → ATR 단위·% 비율로 ② 방향성 이벤트는 부호 있는 수치로
> ③ "지속시간" 류는 시간 수로 ④ 결측은 `null` + 그대로 보존 (오프라인에서 처리 결정)

### L2. 상황 지문 (state fingerprint) — 그룹 분석용 편의 키

"각각의 상황"별 집계를 바로 할 수 있도록 **굵은 버킷**의 이산 키를 함께 저장한다.
(L1 원값이 있으므로 지문 정의는 오프라인에서 언제든 재구성 가능 — 이것은 편의용)

```jsonc
"fp": {
  "regime_1h": "TRENDING",          // 4종
  "regime_4h": "RANGING",           // 4종
  "bias_1d":   "BULL",              // BULL/BEAR/NEUTRAL
  "rsi_zone":  "MID",               // OS(<35)/MID/OB(>65)
  "vol_zone":  "NORMAL",            // SQUEEZE/NORMAL/EXPANDED (bb_width 기준)
  "key": "TRENDING|RANGING|BULL|MID|NORMAL"   // join 키
}
```

- 카디널리티: 4×4×3×3×3 = 432 셀. 표본은 3심볼×24h = **72행/일, 월 ~2,160행** →
  1차 분석은 상위 2~3개 차원(`regime_1h×regime_4h×bias_1d` = 48셀)으로 묶고,
  하위 차원은 표본이 쌓인 뒤 세분화하는 **계층적 사용**을 전제로 한다.

### L3. 참고 메타 (학습 입력 아님 — 봇 로직과의 대조용)

```jsonc
"meta": {
  "score_long":…, "score_short":…, "threshold_long":…, "threshold_short":…,
  "signal_fired": false, "direction": null
}
```

용도: "봇이 신호를 낸 상황 vs 안 낸 상황의 실제 경로 분포 비교", 임계값 적정성 사후 검증.
학습 모델의 입력으로 쓰지 않는다(P5).

---

## 3. 결과 표현 (Phase B) — 72h 전체 경로

기준가 `p0` = 스냅샷 캔들 close. 이후 72개의 1H 캔들 각각에 대해 상대 변화율을 기록한다.

```jsonc
"path": {
  "n": 72,                          // 실제 캡처된 캔들 수 (거래소 결측 시 <72 가능)
  "c": [0.0012, 0.0031, …],        // close_i / p0 − 1   (72개)
  "h": [0.0020, 0.0044, …],        // high_i  / p0 − 1
  "l": [-0.0005, 0.0008, …],       // low_i   / p0 − 1
  "captured_at": "…"
}
```

- 5자리 유효숫자 반올림 → 행당 추가 ~2KB. (월 ~7MB → ~11MB 수준, 허용)
- `atr_pct`가 스냅샷에 있으므로 ATR 단위 변환은 오프라인에서 1줄.

### 이 경로에서 오프라인으로 파생 가능한 것 (예시 — 수집 시 고정하지 않음)

| 파생 라벨 | 계산 |
|-----------|------|
| 임의 호라이즌 수익률 | `c[h−1]` |
| MFE/MAE (임의 구간) | `max(h[:k])`, `min(l[:k])` |
| 도달 시간 | `argmax(h) + 1`, `argmin(l) + 1` (피크/트로프까지 시간) |
| 경로 효율 (추세 vs 왕복) | `|c[−1]| / Σ|Δc|` — 1에 가까우면 일방향, 0이면 왕복 |
| 페이크 브레이크 | `max(h[:6]) > +kσ` 인데 `c[23] < 0` 같은 패턴 정의 자유 |
| 실현 변동성 | `std(Δc) × √(h)` |
| **임의 TP/SL 시뮬레이션** | 어떤 entry/SL/TP/보유시간 조합이든 h/l 경로 위에서 재생 — 봇의 현행 TP/SL 공식 검증 포함 |
| 분류 라벨 | UP/DOWN/FLAT 기준(데드존)을 사후에 자유 설정, 분위수 라벨(quantile binning)도 가능 |

→ v1에서 수집 시점에 박제했던 8개 호라이즌 × 5종 라벨 + 가상 트레이드 판정이 **전부 이 경로의 특수case**가 된다.

---

## 4. 학습 관점의 통계적 주의 (분석 단계 규약 — 문서화 필수)

매시간 표본은 **72h 윈도가 겹치는 자기상관 표본**이다. 이를 무시하면 성과를 과대평가한다.

1. **train/test 분리**: 무작위 분할 금지. **시간순 분할 + 72h embargo**(경계 전후 72h 표본 제외, purged CV).
2. **유효 표본 수**: 겹침 보정 전 명목 n보다 유효 n이 훨씬 작다. 셀별 통계는 비중첩 부분표본(예: 24h 간격 추출)으로 교차 확인.
3. **심볼 혼합**: ATR 단위 표현(P2의 표현 규칙) 덕에 3심볼 풀링 가능하나, `symbol`을 항상 보유 → 풀링/개별 비교.
4. **레짐 드리프트**: `feature_version` + 수집 기간 메타로 구간별 분석. 시장 구조 변화(예: 대세 전환) 전후 분포 비교를 기본 리포트에 포함.
5. **다중 비교**: 432셀 × 여러 라벨로 뒤지면 우연한 "성배"가 반드시 나온다 → 셀 최소 표본 기준(예: n≥100) + out-of-sample 재검증을 규약으로.

---

## 5. 저장/인프라 (v1 결정 유지)

- **저장소**: git 저장소 `data/research/{SYMBOL}/{YYYY-MM}.jsonl` — 심볼별 파일로 3개 병렬 잡 충돌 차단.
- **push**: 실패 시 `fetch + rebase + push` 지수 백오프 5회. 변경 0건이면 커밋 생략.
- **워크플로**: `signal_1h.yml`에 `permissions: contents: write` + 커밋/푸시 스텝.
- **멱등성**: `snapshot_id = symbol + 캔들마감시각` — 재실행 중복 방지.
- **상태 무의존**: 미캡처 행 탐색은 데이터 파일 스캔 — `/tmp/bot_state` 유실 무관.
- **용량**: 행당 ~3.5KB(경로 포함) × 72행/일 ≈ 월 ~8MB. 지난달 파일 gzip 아카이브 옵션.

---

## 6. 모듈 설계 — `src/research_logger.py`

```
research_logger.py
 ├─ build_state(symbol, analysis, pipeline, collected) -> dict
 │    · L1 원시 피처: analysis dict에서 화이트리스트 추출 (점수 산출 이전 값만)
 │    · L2 지문: L1에서 버킷 규칙 적용 (규칙은 config 상수)
 │    · L3 메타: pipeline에서 점수/신호 여부만
 │
 ├─ record_snapshot(state) -> bool          # 멱등 append (path=null)
 │
 ├─ capture_paths(symbol, df_1h) -> int     # ts+72h 경과 & path=null 행 → 경로 기록
 │
 └─ enabled()                               # RESEARCH_LOGGER_ENABLED — 끄면 완전 no-op
```

### main.py 훅 (try/except로 봇 본체 격리 — v1과 동일)

```python
if research_logger.enabled():
    try:
        state = research_logger.build_state(single_symbol, analysis, pipeline, collected)
        research_logger.record_snapshot(state)
        research_logger.capture_paths(single_symbol, collected["ohlcv"]["1h"])
    except Exception as e:
        logger.warning(f"[{single_symbol}] 리서치 로거 오류: {e}")
```

### config.py 추가 상수

```python
RESEARCH_LOGGER_ENABLED = True
RESEARCH_DATA_DIR       = "data/research"
RESEARCH_PATH_HOURS     = 72          # 경로 캡처 길이 (= 캡처 성숙 기준)
RESEARCH_FP_RSI_ZONES   = (35, 65)    # 지문 버킷 경계
RESEARCH_FP_VOL_ZONES   = …           # bb_width 기준 SQUEEZE/NORMAL/EXPANDED 경계
FEATURE_VERSION         = 2
```

### 오프라인 측 (저장소에 함께 두는 분석 유틸 — step 2 후반)

```
analysis/
 ├─ build_dataset.py    # JSONL → 평탄 DataFrame (+ ATR 정규화, 파생 라벨 함수 모음)
 └─ situation_report.py # 지문별 경로 분포 리포트 (n, fwd_ret 분위수, MFE/MAE, 경로효율)
```

---

## 7. v1 → v2 변경 요약

| 항목 | v1 | v2 |
|------|----|----|
| 표본 단위 | 매시간 (신호 무관) | 동일 |
| 피처 | analysis + **점수/보너스/임계값** 혼재 | **점수 이전 원시 지표만** (L1) + 지문(L2), 점수는 참고 메타(L3)로 격리 |
| 결과 | 8개 고정 호라이즌 라벨 + 가상 TP/SL 판정 (수집 시 박제) | **72h close/high/low 전체 경로** — 모든 라벨은 오프라인 파생 |
| 피처 표현 | 원값 그대로 | 절대가 금지·ATR 단위·부호화 등 **표현 규약** 명시 |
| 상황 분석 | 사후 group-by에 의존 | **상황 지문(fp.key)** 내장 + 계층적 사용 지침 |
| 통계 규약 | 없음 | 중첩 표본·embargo·다중 비교 규약 명문화 (§4) |
| 인프라 | git JSONL + rebase-retry | 동일 |

## 8. 구현 단계 (step 2 제안)

| 단계 | 내용 |
|------|------|
| ① | `research_logger.py`: build_state(L1 화이트리스트·L2 버킷·L3) + record_snapshot + capture_paths |
| ② | `config.py` 상수, `main.py` 훅 |
| ③ | `signal_1h.yml` 권한 + 데이터 커밋/푸시 스텝 |
| ④ | 로컬 왕복 테스트: 과거 캔들로 스냅샷 → 72h 경과 가정 → 경로 캡처 → build_dataset 로드 검증 |
| ⑤ | `analysis/build_dataset.py` + `situation_report.py` (지문별 분포 1차 리포트) |
