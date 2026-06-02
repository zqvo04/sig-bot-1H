# 1H Signal Bot (sig-bot-1H) — v4.0

OKX 무기한 선물(USDT-Swap) **1시간봉 스윙 매매** 신호 봇.
멀티 타임프레임(1H·4H·1D) 지표·시장구조·심리·마이크로구조를 종합해 국면(Regime)별 가중 점수를 산출하고, 임계값을 넘는 롱/숏 신호를 텔레그램으로 발송합니다. GitHub Actions에서 매시 정각 +5분에 심볼별 병렬 실행됩니다.

**v4.0 핵심**: ① 신호 보수성 완화(임계 하향 + 누적 인플레이션 캡) ② 추세추종·추세전환(CHoCH) 포착 강화 ③ **TP/SL 자동 산출** ④ **Notion 자동 기록 + 성공/실패 자동 판정**.

> ⚠️ **참고용 신호입니다. 투자 결정과 그 결과는 전적으로 본인 책임입니다.**

---

## 🆕 v4.0 — 대대적 개선 (스윙 최적화 + 자동 성과 추적)

### A. 신호 보수성 완화 (너무 적게 오던 문제 해결)
| 항목 | 변경 | 효과 |
|------|------|------|
| 기본 임계값 | TRENDING 64→**59**, EXPLOSIVE 66→**60**, RANGING 63→**61**, SQUEEZE 66→**63** | 추세 구간 신호 빈도 ↑ |
| **임계 순(純) 인플레이션 캡** | 비극단·비역추세 신호는 `기본임계 ±(−12 / +10)` 이내로 제한 | 수십 개 가산 필터가 누적돼 임계가 80~90까지 치솟아 신호가 질식되던 문제 해소 |
| 세션 조정 | 주말 +6→**+2**, 아시아 +4→**+2** | 크립토 24/7 특성 반영, 비주력 세션 과잉 억제 제거 |
| 보너스 비율 캡 | `0.55→0.65 × base` | 보너스 흡수폭 확대 |

### B. 추세추종 / 추세전환 포착 강화
- **추세정합 진입 완화**: 레짐 TRENDING/EXPLOSIVE + EMA 순방향 + MACD 정합(`_trend_aligned`) → 임계 **−5pt**(초·중기 추세 추가 −2pt). 확정 추세를 적극 포착.
- **추세 성숙도 과잉 억제 완화**: 성숙추세 임계 가산 6→**3pt**.
- **CHoCH(추세전환) 정합 보너스 신설**: 진입 방향과 같은 방향으로의 시장구조 전환에 1h **+8** / 4h **+12pt** (기존엔 역방향 패널티만 존재해 전환 초입을 놓침).
- **극단 반전 임계 완화**: 추세전환(반전) 인식 RSI 임계를 소폭 완화해 반전 세팅을 더 자주 포착.

### C. TP/SL 자동 산출 (`trade_levels.py`)
- 손절 = `max(ATR×2.0, 가격×1.2%)` (상한 5%), 직전 스윙 고/저점이 합리적이면 **구조 손절** 우선.
- 익절 = 손절거리 × **R배수**(등급별 STRONG 2.5 / GOOD 2.0 / WATCH 1.8R).
- 텔레그램 메시지에 진입·SL·TP·리스크% 표기.

### D. Notion 자동 기록 + 성공/실패 자동 판정 (`notion_logger.py`)
- 신호 발생 → Notion DB에 한 행 기록(`Result=OPEN`, 진입/SL/TP/점수/레짐/근거).
- **매 실행마다** OPEN 신호를 1H 캔들로 점검 → **TP 도달 WIN / SL 도달 LOSS** 자동 판정(동시 터치 시 SL 우선).
- 최대 보유 72h 초과 시 시장가 손익부호로 판정(EXPIRED_WIN/LOSS).
- `R Multiple`·`Hold(h)`·`Exit Reason` 기록 → Notion에서 승률·기대값·레짐별 성과를 그룹·필터로 분석.
- 같은 심볼·방향 OPEN 신호가 있으면 중복 기록 방지.

> 📂 **Notion 셋업**: 아래 [Notion 연동](#notion-연동-v40) 참조. 토큰 미설정 시 자동 비활성화되어 봇 본체는 그대로 동작합니다.

---

## 목차
- [핵심 특징](#핵심-특징)
- [동작 방식](#동작-방식)
- [아키텍처 / 파이프라인](#아키텍처--파이프라인)
- [신호 산출 로직](#신호-산출-로직)
- [시장 국면(Regime) 분류](#시장-국면regime-분류)
- [개선 이력 (v3.x)](#개선-이력-v3x)
- [설치 및 실행](#설치-및-실행)
- [배포 (GitHub Actions)](#배포-github-actions)
- [설정 (config.py)](#설정-configpy)
- [프로젝트 구조](#프로젝트-구조)

---

## 핵심 특징

- **멀티 타임프레임(MTF)**: 진입 1H, 중기 4H, 거시 1D를 모두 반영
- **국면 적응형 가중치**: RANGING / TRENDING / EXPLOSIVE / SQUEEZE 별로 지표 가중치·EMA 배율·임계값을 동적으로 변경
- **SMC(Smart Money Concepts)**: FVG, BOS/CHoCH, 피보나치 황금포켓, **오더블록**, **레벨 컨플루언스**
- **시장 심리**: 펀딩비(+추세/쿨링), 롱숏비율, Taker 매수/매도, 청산 감지, OI 매트릭스(+추세 기울기), 스마트머니 괴리
- **마이크로구조 필터**: 호가벽/잔량 불균형, 청산 캐스케이드, 마크/펀딩, 캔들 모멘텀 (별도 페널티)
- **불량신호 방지**: 역풍(headwind) 카운터, 약기본점수 캡, 보너스 비율 캡, 카테고리별 서브캡, 연속신호·가격밴드·동적 쿨다운
- **양방향 대칭**: 롱/숏 로직이 거울처럼 대칭으로 설계
- **텔레그램 리포트**: 점수 근거·임계값 조정 내역·SMC·심리·판단근거를 KST 기준으로 상세 표기

---

## 동작 방식

```
1H 봉 마감(:00) → GitHub Actions 스케줄(:05) → 실행(~:05–08)
   ↓
심볼별 병렬 Job (BTC / ETH / HYPE)
   ↓
데이터 수집 → 분석 → 점수 산출 → (임계 통과 & 쿨다운 통과) → 텔레그램 발송
```

- 펀딩 정산 시각(00/08/16 UTC) 직후 5분 → 정산 노이즈를 흡수한 뒤 실행
- 심볼당 타임아웃 8분, `fail-fast: false`로 한 심볼이 실패해도 나머지는 계속 실행

---

## 아키텍처 / 파이프라인

| 단계 | 모듈 | 역할 |
|------|------|------|
| ① 수집 | `data_pipeline.py` | OHLCV(1H/4H/1D), 펀딩비/이력, 롱숏비율, Taker, OI/이력, 마이크로구조 |
| ② 분석 | `analysis_engine.py` | RSI(MTF)·BB·ADX·EMA·SMC·캔들·시장구조·심리 지표 계산 → `analysis` dict |
| ③ 점수 | `scoring_system.py` | 국면별 가중합 → 배율·게이트·심리배율 → 보너스/패널티 → 임계 판정 |
| ④ 알림 | `notification.py` | 신호 메시지 빌드 + 텔레그램 발송 (HTML) |
| 진입점 | `main.py` | 단일 심볼(`SINGLE_SYMBOL`) 처리, 로깅, 에러 알림 |
| 부가 | `microstructure_analyzer.py` | 호가/청산/마크 기반 마이크로구조 페널티 |

---

## 신호 산출 로직

### 1) 원점수 (국면별 가중합)
[I-1] 펀딩비·롱숏비율은 원점수 가중에서 제외되어 **심리 배율(sentiment multiplier)** 로 이동했습니다. 원점수는 4개 지표의 국면별 가중합입니다.

```
raw_score = Σ ( score[k] × weight[regime][k] )   for k in {rsi, bollinger, taker_volume, volume}
```

### 2) 배율 적용
```
base_score = raw_score × EMA배율 × 게이트페널티 × 심리배율
```
- **EMA 배율**: 1H/4H/1D EMA 정렬 역방향 개수 → 국면별 배율표
- **게이트 페널티**: 펀딩·롱숏이 진입 방향에 불리할 때 (단일 ×0.92 / 복합 ×0.80)
- **심리 배율 [I-1]**: 펀딩·롱숏 유리 정도에 따라 ×1.00 / 1.04 / 1.08

### 3) 보너스 (카테고리별 서브캡 [I-4])
모멘텀 / 구조 / 캔들 / 심리 / 레벨 5개 카테고리로 분류 후 카테고리별 상한 적용 → 단일 카테고리 보너스 폭주 방지.

주요 보너스: 눌림목(강/약/미세), 멀티TF 모멘텀, BOS, HigherLow/LowerHigh, 핀바/인걸핑(1H/4H/1D), FVG, 피보 황금포켓, 주간레벨, **오더블록[II-3]**, **레벨 컨플루언스[II-6]**, **되돌림 적정/깊음[II-1]**, **ADX 가속[II-2]**, **레짐전환[II-4]**, 스마트머니/OI/펀딩추세.

### 4) 패널티
- **소프트 패널티(합산)**: MTF RSI 과열, EXPLOSIVE 소진, 청산 역방향, BOS/CHoCH 역방향, 캔들 모멘텀 역방향 등을 곱연산
- **가산 패널티**: MACD 역방향, FVG 역방향, 거래량 부족, 마이크로구조 합계

### 5) 최종 점수 & 임계 판정
```
final_score = (base_score + bonus_total) × soft_penalty
              + micro_pen + vol_pen + macd_pen + fvg_pen + macd_hist_bonus
signal = final_score >= threshold
```

### 6) 임계값(threshold) 동적 조정
국면 기본값에서 시작해 다음을 가감합니다.
- 메타레짐(4H×1H), 일봉 바이어스, 세션, 펀딩 사이클, 1D-EMA 구조
- 역풍 카운터(A-2) / 하락·상승 모멘텀(A-3) / MA20 위치(C-1)
- RANGING 지속시간(E-1), 연속신호, 4H RSI 극단 완화(C-3)
- **[I-7] 1D RSI 기울기**, **[I-8] 4H·1H 이중 RANGING 억제**
- **[II-1] 되돌림 얕음/붕괴**, **[II-2] ADX 소진**, **[II-4] 추세소진 전환**, **[II-5] 추세 성숙도**
- 극단 과매도/과매수(반전) 조건에서는 다수 억제 필터를 면제하고 임계값 상한(cap)을 적용

---

## 시장 국면(Regime) 분류

`classify_market_regime()`가 ADX·BB 밴드폭·스퀴즈·MA20 교차·효율비(ER)로 분류합니다.

| 국면 | 아이콘 | 조건 요약 | 성격 | 기본 임계 |
|------|--------|-----------|------|-----------|
| SQUEEZE | 🔄 | BB 스퀴즈 + ADX 낮음 | 변동성 압축, 방향 미결정 | 66 |
| EXPLOSIVE | 💥 | ADX 강(≥40) + BB 확장 | 변동성 폭발/추세 가속 | 66 |
| TRENDING | 📈 | ADX 추세(≥25) | 추세 진행 | 64 |
| RANGING | ↔️ | MA20 빈번 교차 / 낮은 ER | 박스권 | 63 |

국면별로 **지표 가중치(`REGIME_SCORE_WEIGHTS`)**, **EMA 배율(`REGIME_EMA_MULTIPLIERS`)**, **임계값(`REGIME_THRESHOLDS`)** 이 달라집니다.

---

## 개선 이력 (v3.x)

### v3.1 ~ v3.4 — 불량신호 방지 / 추세 포착 강화
- 역풍 카운터, RANGING 심리억제, 보너스 비율 캡, 청산 방향 버그픽스, SQUEEZE 메타완화 제거, BOS 보너스 삭감 등

### v3.5 — 스윙 1차 개선 (I 시리즈) + P0 버그픽스
| # | 내용 |
|---|------|
| **P0** | `analyze_mtf_rsi` 키 정정: `value`(1H)·`value_4h`(4H)·`value_1d`(1D) — 이전에 4H/1D가 뒤바뀌어 있던 버그 수정 |
| I-1 | 펀딩·롱숏을 원점수에서 분리 → **심리 배율**(×1.00/1.04/1.08) |
| I-2 | 4H 국면 기반 보너스 분기 (4H추세+1H조정 눌림목 강화 / 4H레인징+1H추세 페이크브레이크 억제) |
| I-3 | 1D 기준 RSI 극단 임계 재보정 |
| I-4 | 카테고리별 보너스 서브캡 |
| I-7 | 1D RSI 기울기 필터 |
| I-8 | 4H·1H 이중 RANGING 임계 상향 |

### v3.6 — 스윙 2차 개선 (II 시리즈)
| # | 요소 | 구현 | 기존 로직 연결 |
|---|------|------|----------------|
| **II-1** | 되돌림 깊이 스코어링 | `analyze_retracement_depth()`(4H) | 4H 추세 구간에서만, 적정 +8 / 깊음 +5 보너스, 얕음·붕괴 임계 가산 |
| **II-2** | ADX 기울기 필터 | `calculate_adx().adx_slope` | 추세정합 시 가속 +6 보너스 / 소진 임계 +5 |
| **II-3** | 오더블록 감지 | `detect_order_blocks()`(1H) | 방향 정합 +8, 컨플루언스에 합류 |
| **II-4** | 레짐 전환 보너스 | prev→현재 전환 | 압축해제 +12 / 박스돌파 +8(4H非레인징 한정) / 추세소진 임계 +10 |
| **II-5** | 추세 성숙도 지수 | `analyze_structure_maturity()`(4H) | 성숙(5+) 임계 +6 / 초기(1~2) 완화 −2 |
| **II-6** | 레벨 컨플루언스 | 점수 단계 통합 | 피보·FVG·OB·주간레벨 2개↑ 중첩 시 개별 보너스를 **흡수·대체**(2개 +8 / 3+ +15) |
| **II-8** | 펀딩 쿨링 반전 | `analyze_funding_history_trend()` | 극단 누적 후 첫 감소 → 역방향 +6 |
| **II-9** | OI 추세 기울기 | `analyze_oi_matrix()` + OI 이력 | OI 추세+가격 정합 +5 (기존 사분면 보너스에 가산) |

> II-7(BTC 상관관계), II-10/11(TP·SL/신호 신선도)은 이번 버전에서 제외(미적용).

---

## 설치 및 실행

### 요구사항
```bash
pip install -r requirements.txt
# ccxt>=4.0.0, pandas>=2.0.0, numpy>=1.24.0, requests>=2.28.0  (Python 3.11)
```

### 환경변수 (Secrets)
| 변수 | 설명 |
|------|------|
| `OKX_API_KEY` / `OKX_API_SECRET` / `OKX_PASSPHRASE` | OKX 읽기용 API 키 |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | 텔레그램 알림 대상 |
| `SINGLE_SYMBOL` | 처리할 심볼 (예: `BTC/USDT`) — Actions matrix가 주입 |

### 로컬 단일 실행
```bash
export OKX_API_KEY=... OKX_API_SECRET=... OKX_PASSPHRASE=...
export TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=...
export SINGLE_SYMBOL="BTC/USDT"
mkdir -p /tmp/bot_state
python src/main.py
```

---

## 배포 (GitHub Actions)

`.github/workflows/signal_1h.yml`

- **스케줄**: `cron: '5 * * * *'` (매시 5분, UTC)
- **매트릭스**: `BTC/USDT`, `ETH/USDT`, `HYPE/USDT` (max-parallel 3, fail-fast false)
- **수동 실행**: `workflow_dispatch` 지원
- **상태 파일**: `/tmp/bot_state/signal_state.json` (쿨다운·연속신호·레짐 지속시간) — 컨테이너 휘발성이라 런 간 일부 상태는 유지되지 않음
- 실패 시 `logs/` 아티팩트 업로드(보존 3일)

> Secrets는 저장소 Settings → Secrets and variables → Actions 에 등록합니다.

---

## 설정 (config.py)

주요 그룹:
- **지표 파라미터**: RSI/BB/ATR/EMA/ADX 기간, 거래량 배수
- **국면별 가중치/배율/임계값**: `REGIME_SCORE_WEIGHTS`, `REGIME_EMA_MULTIPLIERS`, `REGIME_THRESHOLDS`
- **심리 임계값**: 펀딩/롱숏/Taker 기준
- **보너스/패널티 상수**: `BONUS_*`, `*_PENALTY`, 서브캡 `BONUS_SUBCAP_*`
- **쿨다운**: `SIGNAL_COOLDOWN_MINUTES`(240), 가격밴드/동적 쿨다운, 최소 60분 보장
- **v3.5 [I 시리즈]**: `MTF_TREND_*`, `BONUS_SUBCAP_*`, `RSI_1D_SLOPE_*`, `DOUBLE_RANGING_ADJ`
- **v3.6 [II 시리즈]**: `RETRACE_*`, `ADX_SLOPE_*`, `OB_*`, `BONUS_REGIME_TRANSITION_*`, `MATURITY_*`, `BONUS_CONFLUENCE_*`, `BONUS_FUNDING_COOLING`, `OI_TREND_*`

---

## 프로젝트 구조

```
sig-bot-1H/
├── .github/workflows/signal_1h.yml   # 매시 실행 워크플로우 (심볼 병렬)
├── requirements.txt
├── src/
│   ├── main.py                       # 진입점 (단일 심볼 처리 + Notion 평가/기록)
│   ├── config.py                     # 전역 설정/파라미터 (v4.0 포함)
│   ├── data_pipeline.py              # OKX 데이터 수집 (CCXT + REST)
│   ├── analysis_engine.py            # 지표/SMC/심리 분석
│   ├── scoring_system.py             # 점수 산출·임계 판정·쿨다운 (v4.0 로직)
│   ├── microstructure_analyzer.py    # 마이크로구조 페널티
│   ├── trade_levels.py               # [v4.0] TP/SL 산출
│   ├── notion_logger.py              # [v4.0] Notion 기록 + 성공/실패 자동 평가
│   └── notification.py               # 텔레그램 알림 빌더/발송 (TP/SL 표기)
└── README.md
```

---

## Notion 연동 (v4.0)

신호 기록·성과 분석은 Notion DB에 자동 저장됩니다. **봇은 Notion 내부 통합(Integration) 토큰으로 REST API에 직접 기록**하므로, 다음 3단계 셋업이 필요합니다(미설정 시 자동 비활성, 봇 본체는 정상 동작).

### 1) Notion 통합(Integration) 생성
1. https://www.notion.so/my-integrations → **New integration** 생성
2. **Internal Integration Secret**(`ntn_...` 또는 `secret_...`) 복사 → 이것이 `NOTION_TOKEN`

### 2) DB 공유
이미 생성된 **`1H Signal Log`** 데이터베이스(부모 페이지: *📈 1H 시그봇 트레이딩 로그*)를 위 통합에 공유합니다.
- DB(또는 부모 페이지) 우상단 **···** → **연결(Connections)** → 방금 만든 통합 선택
- 데이터베이스 ID(`NOTION_DATABASE_ID`): URL의 `notion.so/<workspace>/<32자리ID>?v=...` 중 32자리 ID
  - 본 워크스페이스 기준: **`aff12b160ec941ada0ce13b01b689e7c`**

> 또는 `NOTION_DATABASE_ID` 대신 `NOTION_PARENT_PAGE_ID`만 주면, 봇이 해당 페이지 하위에 `1H Signal Log` DB를 **자동 생성/재사용**합니다.

### 3) GitHub Secrets 등록
저장소 **Settings → Secrets and variables → Actions** 에 추가:

| Secret | 값 |
|--------|----|
| `NOTION_TOKEN` | 통합 시크릿 토큰 |
| `NOTION_DATABASE_ID` | `aff12b160ec941ada0ce13b01b689e7c` (또는 자동생성 사용 시 생략) |
| `NOTION_PARENT_PAGE_ID` | (선택) 자동 생성용 부모 페이지 ID |

### DB 스키마 (자동 기록 필드)
`Result`(OPEN/WIN/LOSS) · `Symbol` · `Direction` · `Grade` · `Score` · `Threshold` · `Regime 1H/4H` · `Entry` · `Stop Loss` · `Take Profit` · `Exit Price` · `R Multiple` · `ATR %` · `Entry/Resolved Time` · `Hold (h)` · `Exit Reason`(TP_HIT/SL_HIT/EXPIRED_*) · `Reasons` · `Signal ID`

> 승률·기대값 분석: Notion에서 `Result`로 그룹화하거나 `R Multiple` 합계 보드를 만들면 누적 성과를 한눈에 볼 수 있습니다.

---

## 면책 조항

본 소프트웨어는 **교육·연구 목적의 시그널 도구**이며 투자 자문이 아닙니다. 암호화폐 선물 거래는 높은 손실 위험을 동반합니다. 모든 매매 판단과 그 결과에 대한 책임은 사용자 본인에게 있습니다.
