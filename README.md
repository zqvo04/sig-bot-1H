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
L0 VETO(하드): 스프레드폭발 · 진입정면 대량청산캐스케이드 · 데이터신선도실패 ·
   거시정면충돌(TF/BO/MR만 — RV는 면제: CHoCH+리테스트 강제로 본분 보존)
L1 측정·백분위·맥락(features): raw 원시피처 + 자기분포 백분위(pct) + ctx(레짐·거시·바이어스)
   라우팅: regime_1h(+regime_4h 보강) → 허용 셋업 집합. ★거시·바이어스는 라우팅이 아니라
   C축·veto·셀키로 들어간다(라우팅은 레짐만 사용).
L2 셋업 디텍터 ×4 — 직교 3축(C/L/F ∈[-1,1])은 여기서 산출(셋업별 공식 분기):
   C 맥락 : 추종형(_ctx_align)=거시·바이어스·4H추세·일봉EMA20/50 정합 |
            반전형(_ctx_exhaustion)=페이드 대상 추세 신선도
   L 위치 : (close−VWAP/EMA20)/ATR · BB%b 백분위 + 컨플루언스 + 셋업별 구조품질
   F 흐름 : RSI/MACD 소진·동조 + OKX 포지셔닝(펀딩·OI·청산·고래vs군중·테이커)
   ── 디텍터(레짐이 허용집합 결정) ──
   TF: HH/HL + [얕은눌림(1H EMA밴드) ∪ 깊은눌림(4H 피보 50~61.8%)] + 모멘텀/구조 +
       반전봉거래량 (성숙late 추세 확신감쇠) | TP=측정이동 SL=직전스윙∓ATR×1.5 T=48h
   BO: 경계돌파 + 거래량스파이크 + [리테스트 유지★필수] + 펀딩컨트래리언 가점
       (RANGING/SQUEEZE/EXPLOSIVE 도달) | TP=박스높이 SL=박스복귀 T=36h
   MR(RANGING): BB극단 + RSI극단백분위 + 반전마이크로 + 반전봉거래량 |
       TP=박스중심선/반대편경계 SL=박스경계∓ATR T=24h
   RV: 다이버전스 + [CHoCH★필수] + [리테스트(스윕/키레벨거부)★필수] + 반전봉거래량 +
       [≥3확인★] | TP=직전레벨 SL=극단너머 T=48h
L3 보정 승률 P̂: isotonic(로지스틱(C,L,F)) · 셀=(setup×regime_1h×btc_macro)
   └ 신뢰게이트 미충족 → 보수적 고정 prior (콜드스타트)
   └ ★셀 키는 거친 채로 둔다(콜드스타트·과적합 보호). 누락 맥락(4H추세·일봉EMA20/50)은
     셀 키를 늘리는 대신 C축에 연속 피처로 주입 → 셀 내부에서 분리 학습.
L4 발사+청산: 발사 ⟺ P̂ ≥ W_floor ∧ ¬VETO → TP/SL/타임스톱 산출, 사이징 ∝ P̂ (페이퍼)
```

빈도는 넓은 유니버스 × 4셋업 × 양방향의 **합집합**으로 산다(플로어 불변=승률 불변).
BO·RV는 base-rate가 낮아 **강확증된 소수만** 통과한다(P̂ 내림차순 자동 서열화).
**역할 분담**: 하드 베토 = 추종/레인지(TF/BO/MR), 소프트 게이트(C축·min-axis) = 전환(RV).

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

## 신호 로직 상세 (국면분류 · 셋업 · 발사기준)

> "어떤 기준으로 신호를 보내는가"의 완전한 설명. 현재 Phase 0 = 전 셀 prior, 페이퍼,
> `ALERT_ENABLED=false`(텔레그램 OFF, Notion 기록만).

### A. 국면분류 — 3개의 독립 축

레짐은 "무엇을 할지", 거시는 "거스르면 안 되는 큰 방향", 바이어스는 "종목 일봉 방향".

| 축 | 산출(함수) | 값 | 방향성 | 쓰임 |
|----|-----------|-----|--------|------|
| **시장 레짐** | `classify_market_regime` (1H·4H) — ADX+BB스퀴즈+효율비 | TRENDING/EXPLOSIVE/SQUEEZE/RANGING | ❌ | **라우팅**(허용 셋업) + 셀 키(1H) |
| **BTC 거시** | `classify_btc_macro` — BTC 1D 7D변화±3%+EMA20/50 | UPLEG/DOWNLEG/CHOP | ✅ | C축 + **베토** + 셀 키 + 비정상성 층화 |
| **일봉 바이어스** | `analyze_daily_bias` — 일봉 EMA9/21+캔들 | BULL/BEAR/NEUTRAL | ✅ | C축 |

**라우팅**(레짐 → 허용 셋업, `features.allowed_setups`):

| regime_1h | 허용 셋업 | 4H 보강 |
|-----------|----------|---------|
| TRENDING | TF, RV | 4H 추세→TF, 4H 스퀴즈→BO |
| EXPLOSIVE | TF, BO, RV | 〃 |
| SQUEEZE | BO, RV | 〃 |
| RANGING | MR, RV, **BO** | 〃 |
| UNKNOWN | MR | 〃 |

### B. 4 셋업 — 발동조건(precond) · C/L/F · TP/SL

각 셋업은 롱/숏 대칭으로 후보를 만들고, **precond(구조 게이트)를 통과해야** 후보가 된다.
precond는 "강확증" 필터(특히 BO 리테스트·RV CHoCH/리테스트는 필수★).

| 셋업 | 발동 precond (전부 충족) | C / L / F | TP / SL (`levels.py`) |
|------|--------------------------|-----------|------------------------|
| **TF** 추세추종 | 4H EMA정렬 + [얕은눌림(1H EMA밴드) ∪ 깊은눌림(4H피보 50~61.8%)] + (모멘텀 재정렬 ∨ BOS) + 반전봉 거래량 | C=`_ctx_align`(정합) · L=눌림품질(깊을수록↑, 성숙late 감쇠)+컨플루언스 · F=`_flow_align`(모멘텀 동조) | TP=측정이동(R배수 2.5) · SL=직전스윙∓ATR×1.5 · T=48h |
| **BO** 돌파 | 박스경계 돌파(종가) + 거래량스파이크(≥1.5×) + 리테스트 후 유지(2봉)★ + 펀딩 컨트래리언 가점 | C=정합 · L=박스폭+펀딩+컨플루언스 · F=정합 | TP=박스높이 · SL=박스복귀 · T=36h |
| **MR** 평균회귀 | BB %b 극단(≤0.1/≥0.9) + RSI 백분위 극단(≤0.15/≥0.85) + 반전캔들 + 반전봉 거래량 | C=`_ctx_exhaustion`(소진) · L=극단깊이+컨플루언스 · F=`_flow_exhaustion`(컨트래리언) | TP=박스중심선/반대편 · SL=박스경계∓ATR · T=24h |
| **RV** 전환 | 소진≥1 + CHoCH★ + 리테스트(스윕/키레벨거부)★ + 반전캔들★ + 총확인≥3 + 반전봉 거래량 | C=소진 · L=확인수+컨플루언스 · F=컨트래리언 | TP=직전레벨(R배수 2.0) · SL=극단너머 · T=48h |

### C. 직교 3축 산출식 (`detectors.py`, ∈[-1,1])

```
추종형(TF/BO)
  C=_ctx_align    : 0.45·거시 + 0.25·바이어스 + 0.20·4H추세 + 0.10·일봉EMA20/50  (롱+/숏−)
  F=_flow_align   : 0.45·MACD백분위 + 0.25·테이커 + 0.20·스마트머니 + 0.10·OI사분면
반전형(MR/RV)
  C=_ctx_exhaustion: 0.25 + 0.75·(페이드 대상 거시레그 신선도)   ← CHOP 완만통과, 신선역행 차단
  F=_flow_exhaustion: 0.40·RSI소진 + 0.25·펀딩역포지션 + 0.20·테이커소진 + 0.15·스마트머니반대
L(위치, 셋업별): TF 눌림품질 / BO 박스폭 / MR 극단깊이 / RV 확인수
  + 공통 컨플루언스 가점(FVG·OB·피보·주간 중첩수 0~3 × 0.05)
  + TF는 성숙(late)·동방향 추세면 ×0.85 감쇠
```

### D. 발사 기준 (L3→L4)

```
P̂_prior = min( 0.65,  sigmoid( b0[셋업] + 1.1·C + 1.3·L + 1.2·F ) )
   · b0: TF −0.15 / MR −0.25 / BO −0.75 / RV −0.95  (BO·RV는 강확증만 통과)
   · min-axis 게이트: C·L·F 중 하나라도 < 0.10 → P̂=0.55(차단)

발사(fire) ⟺  P̂ ≥ 0.58  ∧  ¬VETO  ∧  (prior면) RR ≥ 1.5
   · VETO(L0): 스프레드폭발 · 청산캐스케이드 · 데이터신선도(>90분)
     · 거시정면충돌(롱+DOWNLEG/숏+UPLEG) — 단 RV는 면제(자체 강게이트로 통제)
   · 발사분 → 사이징 ∝ P̂ → Notion 1H Signal Log 기록 + (ALERT_ON 시) 텔레그램
```

> 신뢰게이트를 통과한 보정 셀은 prior 대신 학습된 `isotonic(로지스틱(C,L,F))`를 쓰고
> RR 필터를 우회한다(학습 승률 존중). **현재 자격 셀 0개 → 전부 prior.**

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
            liq_signal, liq_spike, vol_ratio, rev_vol_ratio, retrace_long/short_zone,
            maturity, maturity_net, hour_utc, dow },
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

## 오프라인 보정 학습 — **중단됨** (`WRF_CALIB_DISABLED=true`)

자격 게이트(탈중첩 독립표본 N≥`n_min`=100 × 거시방향 ≥2종)가 데이터 누적 속도
대비 비현실적으로 높아, 한 셀이 자격을 얻으려면 그 셀에만 후보가 떨어지는 서로
다른 날이 100일+ 필요(거기에 복수 거시국면까지) → 현실적으로 수개월~수년이 걸려
어떤 셀도 보정되지 못했다(**실효 ≈ 0**). 주간 잡은 매번 동일한 "자격 0셀" 빈
결과를 재생산할 뿐이라 **학습을 중단**했다.

- 주간 워크플로우(`.github/workflows/calibrate.yml`) **제거**.
- 라이브는 킬스위치(`WRF_CALIB_DISABLED`, 기본 `true`)로 `calibration_table.json`을
  **무시하고 영구히 보수적 prior(직교게이트)** 만 사용한다.
- 보정 로직(triple-barrier 라벨·purged-CV·베타착시 가드·로지스틱+isotonic)과
  오프라인 스크립트(`analysis/calibrate.py`, `labels.py`)는 **그대로 보존**.
  다시 켜려면 `WRF_CALIB_DISABLED=false` + calibrate 워크플로우를 복구하면 된다.

진단(오프라인): `python analysis/situation_report.py --wrf` (셀별 n·독립n·거시커버리지·승률).

---

## 운영 / 워크플로우

| 워크플로우 | 스케줄 | 역할 |
|------------|--------|------|
| `signal_1h.yml` | 매시 :05 | 수집→측정→엔진(L0~L4)→발사(페이퍼)→스냅샷 적재→Notion 미러 |
| `scoring.yml` | 매 :*/15 | 성숙 경로 채움 + triple-barrier 신호판정 + 스냅샷 라벨 백필 |
| ~~`calibrate.yml`~~ | — | **제거(학습 중단)**. 라이브는 `WRF_CALIB_DISABLED=true`로 prior 고정 |

- **`ALERT_ENABLED`**(Actions Variable, 기본 `false`): 학습기간엔 알림 OFF·기록만.
  커버리지 충족 후 `true`로 전환.
- **Phase 0(지금)**: 전 셀 prior(보수적 직교게이트) + 페이퍼 발사(레거시보다 자주) + 전량 기록.
  다음 단계는 아래 **슈퍼업그레이드 로드맵** 참조(Phase 1 측정 → Phase 2 보정부활 → … 순으로
  검증된 단계만 점등; 알림 ON·실주문은 로드맵 졸업조건 충족 후).
- 무상태(`/tmp` 유실 무관), 심볼별 JSONL이라 병렬 잡 충돌 없음(push 경합은 rebase 백오프).

### 로컬 실행

```bash
pip install -r requirements.txt
export OKX_API_KEY=... OKX_API_SECRET=... OKX_PASSPHRASE=...
export SINGLE_SYMBOL="BTC/USDT"
python src/main.py --mode signal     # 신호(페이퍼) + 스냅샷 적재
python src/main.py --mode score      # 경로 채점 + 신호 판정
python analysis/situation_report.py --wrf    # 셀 진단(오프라인 연구용; 학습은 중단됨)

# [Phase 1] 백테스트/리플레이 하니스 — 저장된 72h 경로로 현 prior 성능 측정
python analysis/backtest.py                   # 전체+setup별 성능 + 게이트 퍼널
python analysis/backtest.py --by setup_macro  # setup×거시별 실현승률·기대R·PF·MaxDD
python analysis/backtest.py --fired-only      # 발사 후보만(실거래 근사)
python analysis/backtest.py --funnel          # 빈도 병목(veto/floor/RR) 퍼널
python analysis/situation_report.py --perf --perf-by cell   # 동일 하니스 위임
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
- **전략 정합 토글**(전부 되돌리기 가능): `WRF_SL_ATR_CUSHION`(구조SL ATR쿠션, 0=구동작),
  `WRF_MR_TP_TARGET`(mid|opposite), `WRF_MR_BOX_WINDOW`, `WRF_RV_REQUIRE_CHOCH/RETEST`(전환
  시퀀스 강제), `WRF_TF_FIB_PULLBACK`(피보 깊은눌림 경로), `WRF_REV_VOL_MULT`(반전봉 거래량
  게이트, 0=OFF), `WRF_BO_FUND_BONUS`(돌파 펀딩 컨트래리언 가점).
- **레이어 연결 토글**: `WRF_BO_IN_RANGING`(RANGING 박스돌파 허용), `WRF_RV_MACRO_EXEMPT`
  (RV 거시베토 면제), `WRF_TF_LATE_MATURITY_MULT`(성숙추세 TF 감쇠, 1.0=없음),
  `WRF_CONFLUENCE_L_BONUS`(컨플루언스→L 가점, 0=OFF).

### 전략 정합 개선 (2026-06, win-rate-first 골격 유지)

스윙 전략 문서 대조 후 측정-발사 정합을 끌어올린 변경. **새 셋업·새 보정셀 없이**
기존 4셋업의 진입·레벨 정밀도만 보강(콜드스타트 불변, 과적합 경계).

- **TF 피보 배선(A1)**: 눌림 판정을 `loc_ema20` 프록시 → `loc 밴드(얕은) ∪ 4H 피보
  optimal/deep(깊은)`. 깊은 눌림은 1H EMA가 추세 반대로 튀므로 **4H 정렬을 게이트**로 포착
  (TF가 못 잡던 50~61.8% 되돌림 진입을 같은 셀로 흡수).
- **구조 SL + ATR 쿠션(G3)**: TF/RV SL을 `직전 스윙 ∓ ATR×1.5`로(노이즈 윅 방지). max 초과
  시 폐기→클램프.
- **MR 박스 기하학(G4)**: TP=박스 중심선/반대편, SL=박스 경계∓ATR(저RR EMA20 회귀 폐기).
- **RV 전환 시퀀스 강제(A4/G6)**: CHoCH 필수 + 리테스트(스윕/키레벨거부) 필수 + 반전봉 필수
  → 첫 반전봉 나이프캐칭 차단.
- **반전봉 거래량 게이트(A5/G7)**: TF/MR/RV 반전봉 거래량 > 직전 5봉 평균. (BO는 돌파봉
  스파이크 유지 + 펀딩 컨트래리언 L 가점.)

### 레이어 연결 완성도 보강 (2026-06, 과적합 경계)

레이어 간 논리 연결 점검에서 드러난 6개 결함 해결. **셀 키 차원은 늘리지 않음**(콜드스타트·
과적합 보호).

- **#1 BO 도달성**: 박스 돌파는 RANGING에서 출발 → `allowed_setups`가 RANGING에도 BO 허용
  (BO precond 강게이트로 노이즈 통제).
- **#2 RV 거시베토 면제**: `MACRO_HEADON`을 RV에서 제외(RV는 CHoCH+리테스트+소진 강제 =
  구조붕괴 증거). 전환 셋업이 거시추세 전환을 칠 수 있게 — 역추세 위험은 C축·min-axis 소프트로.
- **#3 레이어 라벨 정정**: C/L/F 축은 L1이 아니라 **L2(디텍터)** 산출, 라우팅은 **레짐만** 사용
  (거시·바이어스는 C축/veto/셀키 경로) — README 위 엔진도 정정.
- **#4 셀 맥락 혼합**: 셀 키 확장(과적합) 대신, 누락 맥락(4H추세 `ema_4h`·일봉 EMA20/50
  `ema_1d_struct`)을 **C축에 연속 피처로 주입** → 거친 셀 안에서 분리 학습.
- **#5 죽은 연결 복구**: `maturity`(성숙추세 TF 감쇠)·일봉 `ema_structure`(C축) 배선.
- **#6 3중 중복 제거**: 하드 베토(추종/레인지) ↔ 소프트 게이트(전환) 역할 분담으로 정리.
- **완결성#1 컨플루언스 배선**: 측정·기록만 되고 발사엔 미반영이던 `confluence`(FVG/OB/
  피보/주간 중첩수)를 전 셋업 L에 소폭 가점(`min(중첩,3)×0.05`) → 다중 SMC 중첩 진입을
  prior에 반영. 셀·차원 불변(콜드스타트 영향 0).

---

## Notion (2-DB, 기존 DB 재사용)

기존 DB **`1H Signal Log`** / **`1H Research Snapshots`** 를 WRF 양식으로 **개조해 재사용**한다
(이름·기존 데이터 보존, 새 WRF 컬럼 추가, `Exit Reason`에 TIMEOUT 추가, Result→Status·
Take Profit→TP·RSI 1H→RSI 등 일회성 리네임 적용). 토큰 미설정 시 자동 비활성(no-op).

```bash
python scripts/migrate_notion_wrf.py            # 누락 WRF 컬럼만 멱등 추가(스키마 동기화)
python scripts/migrate_notion_wrf.py --purge    # 추가 + 기존 행 전부 아카이브(선택)
```

기본 DB ID는 기존 DB로 설정돼 있다(env로 오버라이드 가능):
`NOTION_SIGNALS_DB_ID`(=레거시 `NOTION_DATABASE_ID`) / `NOTION_SNAPSHOTS_DB_ID`(=`NOTION_RESEARCH_DB_ID`).

- **`1H Signal Log`**(발사된 페이퍼 트레이드): Status(OPEN/WIN/LOSS/TIMEOUT)·Setup·
  Direction·Symbol·Regime 1H/4H·BTC Macro·Entry/TP/SL·R Dist·RR·T_max·P_hat·P Source·
  Win Floor·Size·C/L/F·MFE R·MAE R·Bars To Exit·Exit Reason·Signaled/Resolved At·Reason·Signal ID
  (레거시 Grade·Score·Threshold 등은 참고용으로 잔존)
- **`1H Research Snapshots`**(매시간 학습 미러): TS·Symbol·Snapshot ID·Outcome·Regime/Bias·
  RSI/Vol Zone·BTC Macro·핵심 L1 수치(RSI·BB %b·Dist VWAP/EMA20 ATR·ADX·MACD·Funding·OI·
  Vol Ratio·**Rev Vol Ratio**·**EMA 1D Struct**·**Retrace L/S**·**Maturity(Net)**·
  Confluence L/S 등) + 파생라벨(Ret 4~72h·exRet·MFE/MAE·Class 24/72h·Path Eff·TT) + 후보요약
  (Candidates/Fired). (원시 72h 경로 전체는 git JSONL이 보관; Notion은 필터·그룹용 핵심만.)
  → 새 컬럼은 `python scripts/migrate_notion_wrf.py`로 멱등 추가(누락분만 동기화).

---

## 프로젝트 구조

```
sig-bot-1H/
├── .github/workflows/{signal_1h,scoring}.yml   # calibrate.yml 제거(학습 중단)
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
│   ├── calibrate.py             # 오프라인 보정 잡(보존; 학습 중단·미스케줄)
│   ├── backtest.py              # ★[Phase 1] 백테스트/리플레이 하니스(성능+퍼널)
│   └── situation_report.py      # 상황·WRF 셀 진단(+ --perf 하니스 위임)
├── scripts/migrate_notion_wrf.py
├── data/
│   ├── research/{SYM}/{YYYY-MM}.jsonl
│   └── calibration_table.json   # 라이브가 읽는 유일한 보정 산출물
└── docs/LEARNING_DATA_DESIGN.md
```

> 원칙 재확인: **승률은 보정이 보장, 빈도는 유니버스·4셋업·양방향, 비정상성은
> 거시방향 층화·신뢰게이트가 차단.** 현재 데이터(단일 불런)의 교훈상 처음엔 보정
> 보류·보수적 prior로 출발하고, 다레짐 데이터가 쌓이며 발사권을 셀별로 획득한다.

---

## 슈퍼업그레이드 로드맵 (Super-Upgrade Roadmap)

> 본 로드맵은 2026-06 전면 로직 점검(L0~L4 + 누적데이터 진단) 결과를 반영한
> 단계적 설계다. 각 단계는 **진입조건(Gate-In)** 과 **졸업조건(Gate-Out)** 을
> 명시해, 직전 단계가 정량적으로 검증되기 전에는 다음 단계로 넘어가지 않는다.
> "기능을 더하는 것"이 아니라 **"검증된 엣지를 단계적으로 켜는 것"** 이 원칙이다.

### 현황 진단 (2026-06, 점검 스냅샷)

점검 시점의 사실관계 — 모든 후속 단계는 이 진단을 출발점으로 한다.

| 항목 | 측정값 | 함의 |
|------|--------|------|
| 실효 WRF-4 데이터 | v3 ~115행/심볼 (≈5일) · 레거시 139행은 `btc_macro=None` | 통계적 결론 도출 불가 구간 |
| 거시 커버리지 | v3 구간 = CHOP/DOWNLEG, **UPLEG 0** | 단일레짐 — 대칭성 미검증 |
| 후보/발사 빈도 | 762 스냅샷 → 후보 17 · 발사 7 (**발사율 0.9%**) | **병목 = 빈도**(승률 아님) |
| 보정(L3) | `WRF_CALIB_DISABLED=true`, 자격셀 0 | **심장이 정지** — prior가 100% 결정 |
| 승률 검증 | 라이브·오프라인 실현승률 측정 부재 | "만족스러운 결과"가 **미정량** |

**한 줄 요약**: 지금의 봇은 설계상 "보정이 승률을 보장"하지만, 실제로는 **손튜닝
로지스틱 prior**가 전부를 결정하고 있고(자격게이트가 비현실적으로 높아 보정이 영구
잠듦), 그 prior의 실현 승률조차 측정된 적이 없다. 슈퍼업그레이드의 본질은
**①측정 인프라로 엣지를 정량화 → ②잠든 보정엔진을 현실적 방식으로 부활 →
③발사·사이징·포트폴리오를 고도화 → ④직교 알파를 확장 → ⑤실주문 전환** 이다.

### Phase 1 — 측정·검증 인프라 (✅ 구현 완료) · *"못 재면 못 고친다"*

엣지를 **정량화**하는 단계. 새 알파를 더하기 전에, 이미 매시간 캡처되는 72h 경로를
활용해 현재 prior의 실제 성능을 측정한다. **라이브 코드 무수정·오프라인 전용.**

- ✅ **백테스트/리플레이 하니스 (`analysis/backtest.py`)**: 저장된 `path`(72h OHLC) ×
  `candidates`를 triple-barrier로 재생해 **실현 승률·기대R·Profit Factor·MaxDD·평균보유봉·
  타임아웃%**를 셀(setup×regime×macro)별로 산출. `--fired-only`(실거래 근사)·`--by` 그룹화.
- ✅ **게이트 퍼널 (`--funnel`)**: precond 통과 후보가 **VETO/FLOOR/RR** 중 무엇에 컷되는지
  귀속 → 빈도 병목을 데이터로 식별(precond 컷은 미기록이라 그 이후 단계만 관측).
- ✅ **`situation_report.py --perf` 위임**: 동일 하니스를 기존 리포트 CLI로 호출.
- ✅ **유니버스 확장 (3 → 6, `config.SYMBOLS`)**: +SOL·SUI·XRP(OKX USDT-Swap 고유동).
  빈도·데이터 누적속도를 동시에 끌어올림(셀당 표본 ×2). `env SYMBOLS`로 오버라이드.

> **점검 산출(현 데이터)**: 발사 후보 실현 승률 ≈ 40~50% < 플로어 58%, 빈도 병목은
> 전적으로 **FLOOR(min-axis/p_hat)** 단계(VETO·RR 컷 0). 단, 결판 ~10건·단일레짐이라
> **결론 불가·인프라 검증용**. → Phase 2(보정 부활)로 plug-in 할 측정 토대가 마련됨.
>
> **Gate-Out**: 유니버스 6+ 데이터가 다거시레짐(UP/DOWN/CHOP)을 커버 + 셀별 실현승률
> 테이블이 통계적으로 유의(결판 표본 충분) → Phase 2 진입.

### Phase 2 — 학습 부활: 계층적 베이지안 보정 (중기) · *"심장을 다시 뛰게"*

현 자격게이트(셀당 독립 N≥100 × 거시≥2종)는 수개월~수년이 걸려 **영구히 도달 불가**.
이를 **부분풀링(partial pooling)** 으로 교체해 보정엔진을 현실적으로 되살린다.

- **계층적 로지스틱(shrinkage)**: 셀 추정치를 전역/부모(setup, regime) prior로 수축.
  표본이 적은 셀도 **즉시 사용 가능한 P̂**를 얻고, 데이터가 쌓일수록 자기 셀로 수렴.
  → "자격 0/1" 이분법 폐기, 신뢰도를 **연속적**으로 부여.
- **Purged K-Fold + Embargo CV**(이미 설계됨, `WRF_EMBARGO_HOURS`)로 과적합·자기상관 차단.
- **베타착시 가드**: 라벨을 exret(BTC초과)·triple-barrier로 유지(이미 구축) → "불장 무조건
  롱" 학습 방지.
- **A/B 그림자 평가**: 보정 P̂ vs prior P̂를 동시 기록, 백테스트에서 **out-of-sample**
  보정 우위가 확인될 때만 `WRF_CALIB_DISABLED=false` 전환.

> **Gate-In**: Phase 1 실현승률 테이블 존재. **Gate-Out**: 보정 P̂가 OOS에서 prior 대비
> 캘리브레이션 오차(Brier/ECE)·기대R 우위 → 보정 ON, `calibrate.yml` 워크플로우 복구.

### Phase 3 — 발사·청산·사이징 고도화 (중기) · *"이기는 거래를 키운다"*

승률이 검증되면, **기대값을 극대화**하는 체결·자금관리 레이어로 확장.

- **부분익절 / 트레일링 / 본전스톱**: 현 단일 TP/SL/타임아웃 → 1차 부분익절 후
  ATR 트레일링 + 본전이동(런너 확보). 스윙 추세의 비대칭 페이오프 포착.
- **분수 켈리 사이징**: 현 `size ∝ P̂`(선형) → **frac-Kelly × P̂** (상한·바닥 클램프).
  검증된 셀 승률·RR로 베팅비율을 이론적으로 산출.
- **레짐 적응형 플로어**: 고정 `W_floor=0.58` → 거시/변동성별 동적 플로어(DOWNLEG에서
  롱 플로어 상향 등).
- **상관·포트폴리오 캡**: 동시 다발 상관 포지션(3종 동반롱) 제한 → 진짜 분산 노출 관리.

> **Gate-In**: 보정 ON + 실현승률 ≥ floor 유지. **Gate-Out**: 페이퍼 기대R·MaxDD가
> 부분익절·켈리 적용 후 단조 개선(워크포워드 검증).

### Phase 4 — 직교 알파 확장 (장기) · *"새 정보, 새 엣지"*

검증된 골격 위에서만 **상관 낮은 신규 신호원**을 추가(과적합 경계: 새 셋업은 보정
검증 후에만).

- **신규 데이터축**: 온체인(거래소 유출입·스테이블 수급), 소셜 센티먼트(LunarCrush),
  크로스에셋(BTC.D·DXY·펀딩 term-structure)을 **C/F 축의 연속피처**로 주입(셀키 불변).
- **5번째 셋업(후보)**: 유동성 스윕(stop-hunt) / 펀딩-스퀴즈 반전 — **Phase 2 보정으로
  base-rate 검증된 뒤에만** 라우팅에 편입.
- **메타-레짐 앙상블**: 거시 국면별 셋업 가중을 학습된 게이팅으로 전환.

> **Gate-In**: Phase 2 보정 안정 + 신규축의 단독 IC(정보계수)가 OOS에서 유의.

### Phase 5 — 실전 전환: 페이퍼 → 실주문 (최종) · *"천천히, 안전하게"*

전 단계가 정량 검증된 뒤에만. **자본 보존이 1순위.**

- **체결 현실화**: 슬리피지·수수료·부분체결 모델 → 페이퍼 결과를 디레이팅.
- **세이프티 레일**: 일/주 손실 서킷브레이커, 최대 동시포지션·총노출 한도,
  포지션 정합성 reconciliation, 하트비트 모니터링.
- **그림자 라이브**: 소액 실주문과 페이퍼를 병행해 슬리피지 갭 측정 → 점진 스케일업.
- **다거래소 데이터 이중화**: OKX 단일 SPOF 제거(수집·검증 폴백).

> **Gate-In**: Phase 1~3 졸업 + 최소 1개 다레짐 사이클(UP/DOWN/CHOP) 실현승률 ≥ floor.
> **원칙**: 실주문 스케일은 **검증된 기대값과 MaxDD에 종속**, 감(感)으로 키우지 않는다.

### 횡단 과제 (전 단계 병행)

- **운영 견고성**: 파이프라인 헬스 알림(수집 실패·스냅샷 누락 감지), 워크플로우 관측성.
- **워크포워드 파라미터 튜닝**: 실질 튜닝 3~5개(`WRF_PCT_WINDOW`·`WIN_FLOOR`·
  `CELL_N_MIN` 등)는 단일변수·롤링 워크포워드로만(과적합·곡선맞춤 금지).
- **레거시 정리**: `config.py`의 폐기된 v3/v4/v5 점수제 파라미터(현재 미사용) 단계적 제거.

> **로드맵 불변식**: 어느 단계든 **승률(보정)·빈도(유니버스/셋업/양방향)·비정상성
> (거시층화) 3원칙**을 깨지 않는다. 모든 발사권 확대는 "검증 → 점등" 순서를 지킨다.

## 면책 조항

본 소프트웨어는 교육·연구 목적의 시그널 도구이며 투자 자문이 아닙니다. 암호화폐
선물 거래는 높은 손실 위험을 동반합니다. 모든 매매 판단과 결과의 책임은 사용자에게 있습니다.
