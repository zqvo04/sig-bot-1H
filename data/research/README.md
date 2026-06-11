# Research 데이터셋 — 상태 중심 학습 데이터

`src/research_logger.py`가 매시간 적재하는 **상태 중심(state-centric)** 학습 데이터입니다.
신호 발생 여부와 무관하게 (시장 상태, 이후 72h 차트 경로)를 1행씩 쌓습니다.

## 파일 구조

```
data/research/{SYMBOL}/{YYYY-MM}.jsonl    예: data/research/BTC-USDT/2026-06.jsonl
```

- 심볼별 파일 → BTC/ETH/HYPE 병렬 잡이 서로 다른 파일만 건드려 머지 충돌 없음.
- 한 줄 = JSON 1개(스냅샷). `path`는 처음엔 `null`, 72h 경과 후 Phase B가 채움.

## 행 스키마

| 키 | 의미 |
|----|------|
| `snapshot_id` | `symbol + 봉시각` (멱등키) |
| `ts` | 기준 1H 봉 시각 (UTC ISO) |
| `p0` | 기준가 = 스냅샷 시점 가격 (경로 상대화 기준) |
| `feature_version` | 피처 스키마 버전 |
| `f` | **L1 원시 피처** (RSI/ADX/BB/EMA/SMC/펀딩/OI… 점수 산출 *이전* 값) |
| `fp` | **L2 상황 지문** (`regime_1h\|regime_4h\|bias_1d\|rsi_zone\|vol_zone`) |
| `meta` | **L3 참고 메타** (봇 점수·임계·신호 여부 — 학습 입력 아님) |
| `path` | **72h 경로** `{n, c[], h[], l[]}` = 각 미래봉 `close/high/low ÷ p0 − 1` |

## 오프라인 파생 (라벨은 수집 시 박제하지 않음)

`path`에서 임의 호라이즌 수익률·MFE/MAE·피크도달시간·경로효율·임의 TP/SL 시뮬레이션·
UP/DOWN/FLAT 분류를 자유롭게 계산할 수 있습니다.

## 분석 시 통계 주의

매시간 표본은 72h 윈도가 겹치는 **자기상관 표본**입니다.
시간순 분할 + 72h embargo, 셀 최소표본 n≥100, 다중비교 보정, out-of-sample 재검증을 지킬 것.

> 상세 설계: [`docs/LEARNING_DATA_DESIGN.md`](../../docs/LEARNING_DATA_DESIGN.md)
