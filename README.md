# sig-bot-1H — WRF-4 (Win-Rate-First, 4-Setup)

OKX 무기한 선물(USDT-Swap) **1시간봉 스윙** 신호 봇. **페이퍼 전용**(실주문 없음).

> **목적함수**: `max N_signals s.t. WinRate ≥ W_floor`
> 신호 수를 최대화하되 승률은 플로어 이상으로 보장한다. 정답 메커니즘 =
> **보정된 승률확률 P̂(win) + 임계=플로어**. 보정이 "임계=승률"을 보장하고,
> 빈도는 **넓은 유니버스 × 4셋업 × 양방향**의 합집합으로 산다(플로어 불변).

레거시 v4/v5의 **합산 점수제**(40+ 보너스·임계조정·인플레캡·서브캡)는 전면 제거했다.
"자기 자신과 싸우던" 기계를 버리고, 손으로 튜닝한 가중치 대신 **경로 데이터로 학습한
보정 합산**(로지스틱→isotonic)으로 부활시켰다.

> ⚠️ 참고용 신호입니다. 투자 결정과 결과는 전적으로 본인 책임입니다.

---

## 핵심 철학

- **보정이 승률을 보장**한다. 라이브 봇은 **절대 학습하지 않는다** — 오프라인 주간 잡이
  검증된 셀만 `data/calibration_table.json`으로 배포하고, 라이브는 그 테이블만 읽는다.
- **백분위 상대평가**(절대 임계 금지, 코인별 자기분포), **롱/숏 완전 대칭**,
  **무상태(stateless)**, **try/except로 본체 격리**.
- **비정상성 차단**: 라벨을 방향중립(BTC초과수익 exret + 경로형 triple-barrier)으로 두고,
  매 스냅샷에 **BTC 거시방향 태그**(`btc_macro`: UPLEG/DOWNLEG/CHOP)를 박아 보정을
  거시방향별로 분할한다. 신뢰게이트 미충족 셀은 전부 **보수적 prior**로 동작.

> **왜?** 지금까지 쌓인 학습데이터(약 5.5일·396행)는 **단일 상승장**(UP 71%)이었다.
> "MR롱 승률 100%"는 엣지가 아니라 **시장 베타 착시**다. 유효 독립표본 ~13개로 어떤
> 승률도 통계적 무의미. 나이브하게 학습하면 모델이 "무조건 롱"을 배운다. 그래서
> **처음엔 보정 보류·보수적 prior로 출발**하고, 다레짐 데이터가 쌓이며 셀별로 발사권을 획득한다.

---

## WRF-4 엔진 (5레이어)

```
L0 VETO(하드 ~4): 스프레드폭발 · 진입정면 대량청산캐스케이드 · 데이터신선도실패 · 거시정면충돌
L1 직교 3축(백분위 입력):
   C 맥락 : 레짐 + 거시방향 + 일봉바이어스 → 허용 셋업 라우팅
   L 위치 : (close−VWAP/EMA20)/ATR · BB%b 자기분포 백분위 + 컨플루언스(FVG/OB/피보/주간)
   F 흐름 : RSI/MACD 소진·동조 + OKX 포지셔닝(펀딩백분위·OI사분면·청산스파이크·고래vs군중·테이커)
L2 셋업 디텍터 ×4 (레짐이 허용집합 결정):
   TF(TRENDING+HTF정합): HH/HL + EMA20/VWAP 눌림 + 모멘텀 재정렬 | TP=측정이동 SL=눌림저점 T=48h
   BO(SQUEEZE→확장/박스): 경계돌파 + 거래량스파이크 + [리테스트 유지★필수] | TP=박스높이 SL=박스복귀 T=36h
   MR(RANGING): BB극단 + RSI극단백분위 + 반전마이크로트리거 | TP=VWAP/EMA20 SL=극단+ATR T=24h
   RV(추세소진): 다이버전스 + 키레벨거부 + CHoCH + [≥3확인★] + (청산·펀딩극단·OI플러시) | TP=직전레벨 SL=극단너머 T=48h
L3 보정 승률 P̂: isotonic(로지스틱(C,L,F)) · 셀=(setup×regime×btc_macro)
   └ 신뢰게이트 미충족 → 보수적 고정 prior (콜드스타트)
L4 발사+청산: 발사 ⟺ P̂ ≥ W_floor ∧ ¬VETO → TP/SL/타임스톱 산출, 사이징 ∝ P̂ (페이퍼)
```

빈도는 넓은 유니버스 × 4셋업 × 양방향의 **합집합**으로 산다(플로어 불변=승률 불변).
BO·RV는 base-rate가 낮아 **강확증된 소수만** 통과한다(P̂ 내림차순 자동 서열화).

### 코드 매핑 (`src/wrf/`)

| 모듈 | 레이어 | 역할 |
|------|--------|------|
| `percentile.py` | L1 | 무상태 자기분포 백분위·롤링VWAP·ATR정규화 거리 |
| `btc_macro.py` | L1(C) | BTC 7D/30D·EMA구조 → UPLEG/DOWNLEG/CHOP |
| `features.py` | L1 | 직교 3축(C/L/F) + schema v3 원시피처 + 레짐 라우팅 |
| `detectors.py` | L2 | 4셋업 디텍터(롱숏 대칭, precond 구조게이트) |
| `calibration.py` | L3 | 보정테이블 로더 + 신뢰게이트 + 보수적 prior |
| `veto.py` | L0 | 하드베토 4종 |
| `levels.py` | L4 | 셋업별 구조기반 TP/SL/타임스톱 |
| `engine.py` | L0~L4 | 오케스트레이션, 발사판정, 전량 후보 기록 |
| `schema.py` | — | schema v3 행 빌더 |
| `logger.py` | — | schema v3 멱등 적재 + 경로 캡처 |
| `notion_wrf.py` | — | Notion 2-DB 로거(no-op 가능) |

**측정 레이어 계승**: 레짐분류·MTF지표·SMC·크립토 포지셔닝·reversal_gate 등 측정 로직은
레거시 `analysis_engine.py` / `microstructure_analyzer.py`에서 **순수 측정함수로 재사용**한다
(`run_full_analysis()`는 측정 오케스트레이터로 계승, 점수조립부 `scoring_system.py`는 폐기).

---

## 학습데이터 스키마 (`schema_version: 3`)

월별 JSONL: `data/research/{SYM}/{YYYY-MM}.jsonl`. **한 시간 = 1행**. 라벨은 박제하지
않고 경로에서 오프라인 파생한다. 멱등키 = `symbol + 봉시각`.

```jsonc
{
  "snapshot_id": "...", "ts": "...", "symbol": "...", "schema_version": 3, "p0": 0.0,
  "raw":  { rsi, bb_pctb, dist_vwap_atr, dist_ema20_atr, atr_pct, adx, macd, ema,
            fvg, ob, fib_gp, weekly, confluence_long/short, funding, funding_slope,
            oi_chg, oi_slope, oi_quadrant, ls_long, taker_buy, smart_div,
            liq_signal, liq_spike, vol_ratio, hour_utc, dow },
  "ctx":  { regime_1h, regime_4h, bias_1d, btc_macro, fp_key, allowed_setups },
  "candidates": [ { setup, dir, precond, entry, tp, sl, r_dist, rr, t_max,
                    p_hat, p_source, C, L, F, confluence_n, veto[], size, fire } ],
  "meta": { ... legacy 대조용(학습 입력 아님) ... },
  "path": { n, o[], c[], h[], l[], complete, captured_at }   // 4h부터 증분, 72h 완성
}
```

**오프라인 파생 라벨**(`analysis/labels.py`):
`tb_win[setup]`(배리어 재생=승률 정답) · `ret_Hh`/`exret_Hh`(BTC초과) · `mfe`/`mae` ·
`path_eff` · `class`(exret·데드존 기준 UP/FLAT/DOWN). **triple-barrier·exret이 1차 라벨**
(베타둔감), 원시수익은 보조.

---

## 오프라인 보정 잡 (`analysis/calibrate.py`, 주 1회)

1. JSONL 적재 → `candidate_dataset` (경로에서 triple-barrier + exret 라벨 파생)
2. 셀=(setup×regime×btc_macro) **신뢰게이트**: 탈중첩 독립표본 N≥`n_min` ∧ 거시방향 ≥2종
   (거시 커버리지는 부모 setup×regime 수준에서 평가 — 셀은 거시 1종 고정이므로)
   → 미충족 **prior 유지** / 충족 시 purged-CV(72h embargo) 로지스틱 + isotonic 학습
3. **비정상성 가드**: 셀을 거시방향별로 분할 승률 비교 → 한 방향에서만 성립하면
   **"베타착시" 표기·발사 제외**
4. 피처 가지치기(거시방향 교차 안정 계수)
5. 산출물 `data/calibration_table.json`(셀별 weights·isotonic맵·win_floor·n·coverage·drift)
   → 레포 커밋. **라이브는 이것만 읽는다.**

> 현재 자격 셀 **0개** — 콜드스타트로 전부 prior 동작이 정상이다.

진단: `python analysis/situation_report.py --wrf` (셀별 n·독립n·거시커버리지·승률·자격).

---

## 운영 / 워크플로우

| 워크플로우 | 스케줄 | 역할 |
|------------|--------|------|
| `signal_1h.yml` | 매시 :05 | 수집→측정→엔진(L0~L4)→발사(페이퍼)→스냅샷 적재→Notion 미러 |
| `scoring.yml` | 매 :*/15 | 성숙 경로 채움 + triple-barrier 신호판정 + 스냅샷 라벨 백필 |
| `calibrate.yml` | 주 1회(월) | `calibration_table.json` 갱신·커밋 + 드리프트 리포트 |

- **`ALERT_ENABLED`**(Actions Variable, 기본 `false`): 학습기간엔 알림 OFF·기록만.
  커버리지 충족 후 `true`로 전환.
- **Phase 0(지금)**: 전 셀 prior(보수적 직교게이트) + 페이퍼 발사(레거시보다 자주) + 전량 기록.
  데이터·커버리지 쌓이면 **Phase 3**(P̂ 발사·alert ON).
- 무상태(`/tmp` 유실 무관), 심볼별 JSONL이라 병렬 잡 충돌 없음(push 경합은 rebase 백오프).

### 로컬 실행

```bash
pip install -r requirements.txt
export OKX_API_KEY=... OKX_API_SECRET=... OKX_PASSPHRASE=...
export SINGLE_SYMBOL="BTC/USDT"
python src/main.py --mode signal     # 신호(페이퍼) + 스냅샷 적재
python src/main.py --mode score      # 경로 채점 + 신호 판정
python analysis/calibrate.py         # 보정 테이블 생성
python analysis/situation_report.py --wrf   # 셀 자격 진단
```

---

## 심볼 / 시크릿 / 파라미터

- **심볼**: `BTC/USDT ETH/USDT HYPE/USDT` (확장: SOL/SUI/XRP)
- **Secrets**: `OKX_API_KEY/SECRET/PASSPHRASE`, `TELEGRAM_BOT_TOKEN/CHAT_ID`,
  `NOTION_TOKEN`, `NOTION_SIGNALS_DB_ID` / `NOTION_SNAPSHOTS_DB_ID`(또는
  `NOTION_PARENT_PAGE_ID`로 자동 생성)
- **Variable**: `ALERT_ENABLED`, `WRF_*` 파라미터 오버라이드
- **실질 튜닝(3~5개)**: `WRF_PCT_WINDOW`(백분위 윈도), `WRF_PCT_EXTREME_HI/LO`(극단컷),
  `WRF_WIN_FLOOR`(승률 플로어), `WRF_CELL_N_MIN`(신뢰게이트). 단일변수·워크포워드.

---

## Notion (2-DB, 전면 초기화)

토큰 미설정 시 자동 비활성(no-op) — 봇 본체는 정상 동작. 마이그레이션:

```bash
python scripts/migrate_notion_wrf.py --purge   # 기존 DB 전체 삭제 + 2-DB 생성, ID 출력
```

- **DB1 `WRF Signals`**(발사된 페이퍼 트레이드): Status(OPEN/WIN/LOSS/TIMEOUT)·Setup·
  Direction·Symbol·Regime 1H/4H·BTC Macro·Entry/TP/SL·R Dist·RR·T_max·P_hat·P Source·
  Win Floor·Size·C/L/F·MFE R·MAE R·Bars To Exit·Exit Reason·Signaled/Resolved At·Reason·Signal ID
- **DB2 `WRF Snapshots`**(매시간 학습 미러): TS·Symbol·Snapshot ID·Outcome·Regime/Bias·
  RSI/Vol Zone·핵심 L1 수치 + 파생라벨(Ret 4~72h·exRet·MFE/MAE·Class 24/72h·Path Eff·TT)
  + 후보요약. (원시 72h 경로 전체는 git JSONL이 보관; Notion은 필터·그룹용 핵심만.)

---

## 프로젝트 구조

```
sig-bot-1H/
├── .github/workflows/{signal_1h,scoring,calibrate}.yml
├── src/
│   ├── main.py                  # WRF-4 진입점 (signal/score 모드, 본체 격리)
│   ├── config.py                # 전역 설정 + WRF_* 파라미터
│   ├── data_pipeline.py         # OKX 수집 (계승)
│   ├── analysis_engine.py       # 측정함수 (계승, run_full_analysis=측정 오케스트레이터)
│   ├── microstructure_analyzer.py  # 마이크로구조 측정 (계승)
│   ├── research_logger.py       # 경로 캡처 머신 (스키마 무관·재사용)
│   ├── notion_logger.py         # Notion REST 헬퍼 (notion_wrf가 재사용)
│   └── wrf/                     # ★ WRF-4 엔진 (L0~L4)
│       ├── percentile.py  btc_macro.py  features.py  detectors.py
│       ├── calibration.py  veto.py  levels.py  engine.py  schema.py
│       ├── logger.py  notion_wrf.py
├── analysis/
│   ├── build_dataset.py         # JSONL 로더 + 경로 라벨 헬퍼
│   ├── labels.py                # triple-barrier·exret·class·candidate_dataset
│   ├── calibrate.py             # 오프라인 보정 잡
│   └── situation_report.py      # 상황·WRF 셀 진단 리포트
├── scripts/migrate_notion_wrf.py
├── data/
│   ├── research/{SYM}/{YYYY-MM}.jsonl
│   └── calibration_table.json   # 라이브가 읽는 유일한 보정 산출물
└── docs/LEARNING_DATA_DESIGN.md
```

> 원칙 재확인: **승률은 보정이 보장, 빈도는 유니버스·4셋업·양방향, 비정상성은
> 거시방향 층화·신뢰게이트가 차단.** 현재 데이터(단일 불런)의 교훈상 처음엔 보정
> 보류·보수적 prior로 출발하고, 다레짐 데이터가 쌓이며 발사권을 셀별로 획득한다.

## 면책 조항

본 소프트웨어는 교육·연구 목적의 시그널 도구이며 투자 자문이 아닙니다. 암호화폐
선물 거래는 높은 손실 위험을 동반합니다. 모든 매매 판단과 결과의 책임은 사용자에게 있습니다.
