# 학습 데이터 적재 로직 설계 (Research Logger)

> **목적**: 신호 발송 여부와 **무관하게**, 매 1시간 실행마다 "현재 시장 상황(피처 스냅샷)"을 기록하고,
> N시간 후의 결과(라벨)를 자동으로 채워 **"이런 상황에서 N시간 뒤 이렇게 됐다"** 를 분석/학습할 수 있는
> 데이터셋을 축적한다. 기존 신호 로직·Notion 기록과는 완전히 독립적으로 동작한다.

---

## 1. 핵심 아이디어 — 2단계 파이프라인

봇은 이미 매시 실행되면서 모든 피처(`analysis` + `pipeline`)를 계산하고, 1H 캔들 250개(~10일치)를
매번 수집한다. 따라서 **추가 API 호출 없이** 다음 2단계만 붙이면 된다.

```
매시 실행 (main.py)
 ├─ Phase A: 스냅샷 기록
 │    analysis + pipeline 결과에서 피처를 평탄화(flatten)
 │    → data/research/{SYMBOL}/{YYYY-MM}.jsonl 에 1행 append (labels=null)
 │
 └─ Phase B: 지연 라벨링 (lazy labeling)
      미라벨 행 중 "스냅샷 시각 + 72h(최대 호라이즌)" 가 지난 행을 찾아
      이번 실행에서 이미 수집한 1H 캔들 250개로 모든 호라이즌 라벨을 한 번에 계산
      → 같은 행을 labeled 상태로 갱신
```

- **라벨링은 한 번에**: 가장 긴 호라이즌(72h)이 성숙했을 때 1·2·4·…·72h 라벨을 모두 채운다.
  250개 1H 캔들이면 72h + 여유가 충분하므로 별도 히스토리 조회가 필요 없다.
- **실행 누락 내성**: GHA cron이 몇 번 스킵돼도 라벨링은 타임스탬프 기반이므로 다음 실행에서 자동 보충된다.
  (스냅샷에 구멍이 생길 뿐 — 허용)

---

## 2. 저장소 선택

| 후보 | 장점 | 단점 | 판단 |
|------|------|------|------|
| **git 저장소 (JSONL 커밋)** ✅ | 인프라/Secret 추가 없음, 영속·버전관리, pandas로 바로 로드 | 매시 커밋 발생, 병렬 잡 push 경합 | **채택** |
| Notion DB | 이미 연동돼 있음 | 시간당 3행×24h=연 2.6만 행 → API 페이지네이션·rate limit, ML용 export 불편 | 부적합 |
| Supabase/외부 DB | SQL 질의 편리 | Secret·스키마 관리 추가, 의존성 증가 | 규모 커지면 2차 후보 |
| GHA cache (`/tmp/bot_state`) | 이미 사용 중 | 7일 evict·유실 가능 → 데이터셋 저장소로 부적격 | 불가 |

### git 저장 상세
- **위치**: 코드와 같은 저장소의 `data/research/` 디렉터리. 데이터 커밋이 코드 히스토리에 섞이는 것이
  싫다면 orphan `dataset` 브랜치로 분리할 수 있으나, checkout/worktree 처리가 복잡해지므로
  **1차는 실행 브랜치에 직접 커밋**으로 시작하고, 부담되면 분리한다.
- **파일 분할**: `data/research/{SYMBOL}/{YYYY-MM}.jsonl` — 심볼별 파일이라 BTC/ETH/HYPE
  3개 병렬 잡이 **서로 다른 파일**만 건드림 → 머지 충돌 없음.
- **push 경합 해결**: 3개 잡이 거의 동시에 push하므로 실패 시
  `git fetch + rebase + push` 를 지수 백오프로 최대 5회 재시도. (파일이 분리돼 있어 rebase는 항상 성공)
- **워크플로 변경**: `signal_1h.yml`에 `permissions: contents: write` + 봇 실행 후
  `git add data/ && commit && push(재시도)` 스텝 추가. 변경이 없으면(스냅샷/라벨 갱신 0건) 커밋 생략.
- **용량 추정**: 행당 ~3KB × 72행/일 ≈ 월 ~7MB, 연 ~80MB. 월별 파일이므로 필요 시 지난달 파일 gzip 아카이브.

---

## 3. 스냅샷 스키마 (Phase A)

`feature_version` 필드로 스키마 진화를 관리한다(피처 추가는 nullable로만).

```jsonc
{
  // ── 메타 ──
  "snapshot_id": "BTC/USDT_2026-06-11T13:00:00Z",  // symbol + 캔들마감시각 → 멱등키(중복 append 방지)
  "ts": "2026-06-11T13:00:00Z",                    // 기준 = "마감된 1H 캔들의 close 시각" (실행시각 아님!)
  "symbol": "BTC/USDT",
  "feature_version": 1,
  "labeled": false,

  // ── 시장 상태 (기준 캔들) ──
  "px": { "open":…, "high":…, "low":…, "close":…, "volume":… },
  "atr_pct": 1.42,

  // ── 지표 ──
  "ind": {
    "rsi_1h":…, "rsi_4h":…, "rsi_1d":…, "rsi_1d_slope":…,
    "bb_pos":…, "bb_width":…, "bb_squeeze":…,
    "adx":…, "adx_slope":…,
    "ema_align_1h":…, "ema_align_4h":…, "ema_align_1d":…,   // 정/역방향 정렬 상태
    "macd_state":…, "macd_hist":…,
    "volume_ratio":…
  },

  // ── 레짐/컨텍스트 ──
  "regime": { "r1h":"TRENDING", "r4h":"RANGING", "daily_bias":"BULL",
              "regime_duration_h":…, "prev_regime":… },

  // ── 구조/SMC ──
  "smc": { "bos_1h":…, "choch_1h":…, "bos_4h":…, "fvg":…, "order_block":…,
           "fib_golden_pocket":…, "weekly_level":…, "confluence_count":…,
           "retrace_depth_state":…, "maturity_index":…,
           "higher_low":…, "lower_high":…, "pinbar_1h":…, "engulfing_1h":… },

  // ── 심리 ──
  "sent": { "funding":…, "funding_trend":…, "funding_cooling":…,
            "ls_ratio":…, "taker_ratio":…,
            "oi_change":…, "oi_trend_slope":…, "smart_money_div":…, "liq_side":… },

  // ── 마이크로구조 ──
  "micro": { "ob_imbalance":…, "wall":…, "cascade":…, "mark_funding":…, "penalty_total":… },

  // ── 점수 (양방향 모두 — 신호 안 떠도 기록) ──
  "score": {
    "long":  { "raw":…, "base":…, "bonus":…, "soft_pen":…, "final":…, "threshold":… },
    "short": { "raw":…, "base":…, "bonus":…, "soft_pen":…, "final":…, "threshold":… },
    "signal_fired": false, "direction": null, "cooldown_skip": false
  },

  // ── 가상 트레이드 레벨 (라벨 단계에서 시뮬레이션 평가용 — trade_levels.py 재사용) ──
  "hypo": {
    "long":  { "entry":…, "sl":…, "tp":… },
    "short": { "entry":…, "sl":…, "tp":… }
  },

  "labels": null   // Phase B에서 채움
}
```

> **피처 추출 방식**: `analysis`/`pipeline` dict 전체를 덤프하지 않고 **명시적 화이트리스트**로
> 평탄화한다. (dict 전체 덤프는 DataFrame 깨짐·용량 폭증·스키마 불안정의 원인)

---

## 4. 라벨 스키마 (Phase B)

기준가 `p0` = 스냅샷 캔들 close (ticker 현재가 아님 — 실행 지연 ±5~8분 노이즈 배제).
호라이즌 `H = {1, 2, 4, 8, 12, 24, 48, 72}` (config 상수화).

각 호라이즌 h에 대해, 스냅샷 이후 h개의 1H 캔들 `c_1..c_h`로:

| 라벨 | 정의 | 용도 |
|------|------|------|
| `fwd_ret_{h}` | `(close_h − p0) / p0` | 기본 수익률 |
| `mfe_{h}` | `(max(high_1..h) − p0) / p0` | 최대 우호 변동 (롱 관점 run-up) |
| `mae_{h}` | `(min(low_1..h) − p0) / p0` | 최대 역행 변동 (롱 관점 drawdown) |
| `fwd_ret_atr_{h}` | `fwd_ret_h / atr_pct` | ATR 정규화 — 심볼/변동성 간 비교 가능 |
| `class_{h}` | UP / DOWN / FLAT (데드존: \|ret\| < `0.25 × atr_pct`, config화) | 분류 학습용 |

추가로 **가상 트레이드 시뮬레이션** (양방향 모두, 신호 발생 여부 무관):

```
hypo_long / hypo_short:
  notion_logger의 판정 규칙 재사용 —
  · LONG: low ≤ SL → LOSS / high ≥ TP → WIN / 동시 터치 → SL 우선
  · 72h 내 미체결 → TIMEOUT (그 시점 손익 부호 기록)
  → { outcome: WIN|LOSS|TIMEOUT, hold_h:…, r_multiple:… }
```

이 라벨이 있으면 "점수 X·레짐 Y에서 롱 잡았으면 어떻게 됐나"를 **모든 시간대**에 대해 분석할 수
있어, 임계값 튜닝·필터 검증을 실제 발송 신호(소수)보다 훨씬 큰 표본으로 할 수 있다.

---

## 5. 모듈 설계 — `src/research_logger.py` (신규)

```
research_logger.py
 ├─ record_snapshot(symbol, analysis, pipeline, collected) -> bool
 │    · 마감 캔들 ts로 snapshot_id 생성 → 파일 마지막 행과 비교해 중복이면 skip (멱등)
 │    · _flatten_features() 화이트리스트로 피처 추출
 │    · trade_levels.compute_trade_levels()를 양방향 호출해 hypo 레벨 저장
 │    · 월별 JSONL append
 │
 ├─ label_matured_snapshots(symbol, df_1h) -> int   # 갱신 행 수 반환
 │    · 당월+전월 파일에서 labeled=false & ts+72h ≤ now 인 행 검색
 │    · df_1h(이번 실행 수집분)에서 ts 이후 캔들 슬라이스 → 라벨 계산
 │    · 행 갱신(파일 rewrite — 월별 파일이라 수천 행 수준, 부담 없음)
 │
 └─ enabled()  # RESEARCH_LOGGER_ENABLED (config/env) — 끄면 완전 no-op
```

### main.py 훅 (각 1곳, 실패해도 봇 본체에 영향 없도록 try/except)

```python
# 3. 점수 산출 직후
if research_logger.enabled():
    try:
        research_logger.record_snapshot(single_symbol, analysis, pipeline, collected)
        research_logger.label_matured_snapshots(single_symbol, collected["ohlcv"]["1h"])
    except Exception as e:
        logger.warning(f"[{single_symbol}] 리서치 로거 오류: {e}")
```

### config.py 추가 상수

```python
RESEARCH_LOGGER_ENABLED = True
RESEARCH_DATA_DIR       = "data/research"
RESEARCH_HORIZONS_H     = [1, 2, 4, 8, 12, 24, 48, 72]
RESEARCH_FLAT_DEADZONE  = 0.25     # FLAT 분류 데드존 (× ATR%)
RESEARCH_MAX_HOLD_H     = 72       # 가상 트레이드 최대 보유 (라벨 성숙 기준)
```

---

## 6. 주의사항 / 설계 결정

1. **Lookahead 방지**: 스냅샷의 모든 피처는 마감 캔들 기준 — 기존 파이프라인 동작 그대로.
   라벨 기준가도 캔들 close로 통일해 실행 지연(±5~8분)에 따른 노이즈를 제거.
2. **멱등성**: `snapshot_id = symbol + 캔들마감시각`. 같은 시간대 재실행(수동 dispatch 등) 시 중복 append 안 함.
3. **상태 의존 없음**: 미라벨 행 탐색은 데이터 파일 자체를 스캔하므로 `/tmp/bot_state` 유실과 무관.
4. **스키마 진화**: `feature_version` 증가 + 신규 필드는 추가만(기존 필드 의미 변경 금지).
   분석 시 버전별 필터 가능.
5. **봇 본체 격리**: 모든 진입점이 try/except + enabled() 가드 — 로거 장애가 신호 발송을 막지 않음.
6. **push 경합**: 심볼별 파일 분리 + rebase-retry. 그래도 실패하면 해당 런 데이터는 다음 런 라벨링엔
   영향 없고 스냅샷 1개 누락에 그침(치명적이지 않음).

---

## 7. 구현 단계 (step 2 제안)

| 단계 | 내용 |
|------|------|
| ① | `src/research_logger.py` 작성 (flatten 화이트리스트 + 라벨러 + 시뮬레이터) |
| ② | `config.py` 상수 추가, `main.py` 훅 2줄 |
| ③ | `signal_1h.yml`: `permissions: contents: write` + 데이터 커밋/푸시 스텝 (rebase-retry) |
| ④ | 로컬 검증: 과거 캔들로 스냅샷→72h 경과 가정→라벨링 왕복 테스트 |
| ⑤ | (운영 후) 월별 gzip 아카이브, 분석 노트북(`analysis/`) 추가 |
