# sig-bot-1H — WRF-4 (Win-Rate-First, 4-Setup)

OKX 무기한 선물(USDT-Swap) **1시간봉 스윙** 신호 봇. **페이퍼 전용**(실주문 없음).

> **목적함수**: `max N_signals s.t. WinRate ≥ W_floor`
> 신호 수를 최대화하되 승률은 플로어 이상으로 보장한다. 정답 메커니즘 =
> **보정된 승률확률 P̂(win) + 임계=플로어**. 보정이 "임계=승률"을 보장하고,
> 빈도는 **넓은 유니버스 × 4셋업 × 양방향**의 합집합으로 산다(플로어 불변).

레거시 v4/v5의 **합산 점수제**(40+ 보너스·임계조정·인플레캡·서브캡)는 전면 제거했다.
"자기 자신과 싸우던" 기계를 버리고, 손으로 튜닝한 보수적 prior 위에 **경로 데이터로 학습한
계층적 부분풀링 보정**(Phase 2: prior 기울기 고정 + 셀별 절편 δ만 수축학습)을 얹었다.

> ⚠️ 참고용 신호입니다. 투자 결정과 결과는 전적으로 본인 책임입니다.

---

<a id="status"></a>
## 현재 상태 한눈에

```
수집(OKX,ccxt 읽기전용) → 측정(L1 raw/pct/ctx) → 4셋업 디텍터(L2, C/L/F)
   → 보정(L3, 그림자) → 발사판정(L4, P̂≥floor∧¬VETO) → JSONL+Notion 기록
   → (오프라인, 매주) 부분풀링 학습 → calibration_table.json → 다음 주 라이브가 δ_eff만 읽음
```

| 항목 | 상태 |
|---|---|
| 실주문 | **없음** — 전량 페이퍼(advisory) |
| 알림(텔레그램) | `ALERT_ENABLED=true` — Notion 기록만, 학습기간 중 |
| 보정(L3) | `WRF_CALIB_DISABLED=true` — 발사는 **prior**, 보정 P̂은 그림자 기록만 |
| BR(밴드반전) 발사권 | `WRF_SHADOW_SETUPS={"BR"}` — 후보생성·기록은 하되 라이브 발사는 안 함 |
| **P0/P1/P2 실험** | **2026-07-04부로 기본 ON**(사용자 지시 라이브 실험) — [토글 레퍼런스](#toggles) · [실험 로그](#changelog) 참조 |
| **C축 V5 실험** | **2026-07-04부로 기본 ON**(사용자 지시 FN-최소화 라이브 실험) — 반전C=v2(`WRF_REV_CTX_V2`)·추종 리클레임부스트(`WRF_CTX_RECLAIM_BOOST`). [실험 로그](#changelog) 참조 |
| 데이터 커버리지 | 거시레짐 UPLEG 관측 **0건**(DOWNLEG/CHOP만) — 롱측 검증은 여전히 보류 상태 |

---

<a id="toc"></a>
## 목차

- [핵심 철학](#philosophy)
- [WRF-4 엔진 로직 구조 (5레이어)](#engine)
- [신호 로직 상세](#signal-logic)
- [학습데이터 스키마](#schema)
- [오프라인 보정 학습](#calibration)
- [셋업 인큐베이터 운영 가이드](#incubator)
- [운영 / 워크플로우](#ops)
- [토글 레퍼런스 (ON/OFF 전체 일람)](#toggles)
- [심볼 / 시크릿](#symbols)
- [Notion](#notion)
- [프로젝트 구조](#structure)
- [실험 로그 (히스토리)](#changelog)
- [슈퍼업그레이드 로드맵](#roadmap)
- [면책 조항](#disclaimer)

---

<a id="philosophy"></a>
## 핵심 철학

- **보정이 승률을 보장**한다. 라이브 봇은 **절대 학습하지 않는다** — 오프라인 주간 잡이
  부분풀링 δ_eff를 `data/calibration_table.json`으로 배포하고, 라이브는 그 테이블만 읽는다.
- **백분위 상대평가**(절대 임계 금지, 코인별 자기분포), **롱/숏 완전 대칭**,
  **무상태(stateless)**, **try/except로 본체 격리**.
- **비정상성 차단**: 라벨을 방향중립(BTC초과수익 exret + 경로형 triple-barrier)으로 두고,
  매 스냅샷에 **BTC 거시방향 태그**(`btc_macro`: UPLEG/DOWNLEG/CHOP)를 박아 보정을
  거시방향별로 분할한다. 보정 데이터가 적은 셀은 부모로 수축돼 **사실상 prior**로 동작
(δ_eff→0), 데이터가 쌓일수록 자기 셀 보정으로 수렴한다.

> **왜?** 지금까지 쌓인 학습데이터(약 5.5일·396행)는 **단일 상승장**(UP 71%)이었다.
> "MR롱 승률 100%"는 엣지가 아니라 **시장 베타 착시**다. 유효 독립표본 ~13개로 어떤
> 승률도 통계적 무의미. 나이브하게 학습하면 모델이 "무조건 롱"을 배운다. 그래서
> **처음엔 보정 보류·보수적 prior로 출발**하고, 다레짐 데이터가 쌓이며 셀별로 발사권을 획득한다.

---

<a id="engine"></a>
## WRF-4 엔진 (5레이어)

```
L0 VETO(하드): 스프레드폭발 · 진입정면 대량청산캐스케이드 · 데이터신선도실패 ·
   거시정면충돌(TF/BO/MR만 — RV는 면제: 소진+반전 증거 + min-axis 소프트게이트로 통제)
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
       (WRF_TF_TRAIL ON 시 TP 대신 HWM∓ATR 트레일링·T=72h — 토글 레퍼런스 참조)
   BO: 경계돌파 + 거래량스파이크 + [리테스트 유지★필수] + 펀딩컨트래리언 가점
       (RANGING/SQUEEZE/EXPLOSIVE 도달) | TP=박스높이 SL=돌파경계 near∓ATR(RR정상화) T=36h
   MR(RANGING): BB극단 + RSI극단백분위 + 반전마이크로 + 반전봉거래량 |
       TP=박스중심선/반대편경계 SL=박스경계∓ATR T=24h
   RV: 다이버전스 + 반전캔들 + [확인≥2] + 반전봉거래량 (CHoCH·리테스트는 소프트=L감쇠) |
       TP=직전레벨 SL=극단너머 T=48h
   밴드반전(RV·원트랙): BB 밴드복귀(상단→복귀=숏/하단→복귀=롱) — 후보 생성은 라이브,
       발사권은 섀도 강등(setup=BR, WRF_SHADOW_SETUPS)
L3 보정 승률 P̂: isotonic(로지스틱(C,L,F)) · 셀=(setup×regime_1h×btc_macro)
   └ 신뢰게이트 미충족 → 보수적 고정 prior (콜드스타트)
   └ ★셀 키는 거친 채로 둔다(콜드스타트·과적합 보호). 누락 맥락(4H추세·일봉EMA20/50)은
     셀 키를 늘리는 대신 C축에 연속 피처로 주입 → 셀 내부에서 분리 학습.
L4 발사+청산: 발사 ⟺ P̂ ≥ W_floor ∧ ¬VETO ∧ ¬격리[Phase A: 섀도셋업(BR)·발사권강등 셀]
   → TP/SL/타임스톱 산출, 사이징 ∝ P̂ (페이퍼)
   ★같은 코인 OPEN 중 같은 방향 추가 발사 금지(반대 방향은 허용) — 방향 단위 중복 격리.
     지속 OPEN(Notion 원장) + 동일 실행 다중 셋업 모두 방향으로 묶어 최고 P̂만 발사.
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
| `calibration.py` | L3 | 보정테이블 로더 + 부분풀링 δ_eff 소비 + prior(그림자 A/B) |
| `veto.py` | L0 | 하드베토 4종 |
| `levels.py` | L4 | 셋업별 구조기반 TP/SL/타임스톱(+ TF 트레일링 주석) |
| `engine.py` | L0~L4 | 오케스트레이션, 발사판정, 전량 후보 기록 |
| `schema.py` | — | schema v3 행 빌더 |
| `logger.py` | — | schema v3 멱등 적재 + 경로 캡처 |
| `notion_wrf.py` | — | Notion 2-DB 로거(no-op 가능) |

**측정 레이어 계승**: 레짐분류·MTF지표·SMC·크립토 포지셔닝·reversal_gate 등 측정 로직은
레거시 `analysis_engine.py` / `microstructure_analyzer.py`에서 **순수 측정함수로 재사용**한다
(`run_full_analysis()`는 측정 오케스트레이터로 계승, 점수조립부 `scoring_system.py`는 폐기).

---

<a id="signal-logic"></a>
## 신호 로직 상세 (국면분류 · 셋업 · 발사기준)

> "어떤 기준으로 신호를 보내는가"의 완전한 설명. 현재 Phase 0 = 전 셀 prior, 페이퍼,
> `ALERT_ENABLED=false`(텔레그램 OFF, Notion 기록만).

### A. 국면분류 — 3개의 독립 축

레짐은 "무엇을 할지", 거시는 "거스르면 안 되는 큰 방향", 바이어스는 "종목 일봉 방향".

| 축 | 산출(함수) | 값 | 방향성 | 쓰임 |
|----|-----------|-----|--------|------|
| **시장 레짐** | `classify_market_regime` (1H·4H) — ADX+BB스퀴즈+ER백분위+방향지속(드리프트게이트) | TRENDING/EXPLOSIVE/SQUEEZE/RANGING | ❌ | **라우팅**(허용 셋업) + 셀 키(1H) |
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
precond는 구조 필터(BO 리테스트는 필수★; RV는 소프트화 — 소진+반전캔들만 필수, CHoCH/리테스트는 L 감쇠로 흡수 → floor가 최종 품질게이트).

| 셋업 | 발동 precond (전부 충족) | C / L / F | TP / SL (`levels.py`) |
|------|--------------------------|-----------|------------------------|
| **TF** 추세추종 | 4H EMA정렬 + [얕은눌림(1H EMA밴드) ∪ 깊은눌림(4H피보 50~61.8%)] + (모멘텀 재정렬 ∨ BOS) + 반전봉 거래량 | C=`_ctx_align`(정합, fast-struct 옵션) · L=눌림품질(깊을수록↑, 성숙late 감쇠)+컨플루언스 · F=`_flow_align`(모멘텀 동조) | TP=측정이동(R배수 2.5) · SL=직전스윙∓ATR×1.5 · T=48h (트레일링 ON 시 HWM∓ATR·T=72h) |
| **BO** 돌파 | 박스경계 돌파(종가) + 거래량스파이크(≥1.5×) + 리테스트 후 유지(2봉)★ + 펀딩 컨트래리언 가점 | C=정합 · L=박스폭+펀딩+컨플루언스 · F=정합 | TP=박스높이 · SL=**돌파경계 near∓ATR**(RR≈박스/ATR) · 타이트시 P̂보정 · T=36h |
| **MR** 평균회귀 | BB %b 극단(≤0.1/≥0.9) + RSI 백분위 극단(`WRF_PCT_EXTREME`=0.15/0.85) + 반전캔들 + 반전봉 거래량 | C=`_ctx_exhaustion`(소진) · L=극단깊이+컨플루언스 · F=`_flow_exhaustion`(컨트래리언) | TP=박스중심선/반대편 · SL=박스경계∓ATR · T=24h |
| **RV** 전환 | 소진≥1 + 반전캔들★ + 총확인≥2 **(CHoCH·리테스트는 소프트 — 하드 아님, 부재 시 L 감쇠)** + 반전봉 거래량 | C=소진(리클레임-킬 옵션) · L=확인수−(CHoCH/리테스트 부재 감쇠)+컨플루언스 · F=컨트래리언 | TP=직전레벨(R배수 2.0) · SL=극단너머 · T=48h |

### C. 직교 3축 산출식 (`detectors.py`, ∈[-1,1])

```
추종형(TF/BO)
  C=_ctx_align    : 0.45·거시 + 0.25·바이어스 + 0.20·4H추세 + 0.10·일봉EMA20/50  (롱+/숏−)
    · [P1] WRF_CTX_FAST_STRUCT(기본 ON): 거시 가중(0.45)의 일부(기본 0.20)를 자기 1H
      빠른구조(_fast_struct: bos/choch·failed_break·ema·VWAP)로 이관, 가중합=1 보존.
  F=_flow_align   : 0.45·MACD백분위 + 0.25·테이커 + 0.20·스마트머니 + 0.10·OI사분면
반전형(MR/RV/BR)
  C=_ctx_exhaustion: 0.25 + 0.75·(페이드 대상 거시레그 신선도)   ← CHOP 완만통과, 신선역행 차단
    · [Phase C] v2(WRF_REV_CTX_V2, 기본 OFF): 0.25 + 0.75·(심볼-로컬 구조정합 _ctx_struct_align)
      = macro echo 포화(고유값 3개) 해소 · envelope[-0.5,1.0]·극단 불변, 중간 해상도만 추가
    · [Phase C-v4] 임펄스킬(WRF_REV_IMPULSE_KILL, 기본 ON): 페이드 대상이 극단 스트레치 +
      단기구조 생존이면 C=−0.5 강제(신선 임펄스 페이드 금지).
    · [P0] 리클레임킬(WRF_REV_RECLAIM_KILL, 기본 ON): 페이드 대상이 자기 1H 구조로 이미
      리클레임(구조플립+VWAP+EMA ≥2)했으면 C를 −1.0으로 하드차단(임펄스킬보다 조기 발동).
  F=_flow_exhaustion: 0.40·RSI소진 + 0.25·펀딩역포지션 + 0.20·테이커소진 + 0.15·스마트머니반대
L(위치, 셋업별): TF 눌림품질 / BO 박스폭 / MR 극단깊이 / RV 확인수
  + 공통 컨플루언스 가점(FVG·OB·피보·주간 중첩수 0~3 × 0.05)
  + TF는 성숙(late)·동방향 추세면 ×0.85 감쇠
```

### D. 발사 기준 (L3→L4)

```
P̂_prior = min( 0.65,  sigmoid( b0[셋업] + 1.1·C + 1.3·L + 1.2·F − min-axis 페널티 ) )
   · b0: TF −0.15 / MR −0.25 / BO −0.75 / RV −0.95  (BO·RV는 강확증만 통과)
   · min-axis: 약한 축(<0.10) '부족분'에 비례하는 **연속 페널티**(2.5×deficit) — 구 0.55 절벽 폐기.
     0.10 근방 매끄럽게 회복(near-miss FN↓), 음수축(역추세)은 급차단(FP↓). prior·보정 일관.

발사(fire) ⟺  P̂ ≥ 0.58  ∧  ¬VETO  ∧  (prior면) **EV-게이트**[ EV=P̂·RR−(1−P̂) ≥ 0.15 ∧ RR ≥ 0.85 ]
             ∧  ¬**격리**[Phase A: 섀도셋업(WRF_SHADOW_SETUPS, 기본 BR) ∨ 발사권 강등 셀]
   · VETO(L0): 스프레드폭발 · 청산캐스케이드 · 데이터신선도(>90분)
     · 거시정면충돌(롱+DOWNLEG/숏+UPLEG) — 단 RV·BR은 면제(자체 강게이트로 통제)
   · 격리 후보는 발사만 차단 — 기록·오프라인 채점은 계속(quarantine 태그, 복권 증거 축적)
   · 발사분 → 사이징 ∝ P̂ → Notion 1H Signal Log 기록 + (ALERT_ON 시) 텔레그램
```

> 신뢰게이트를 통과한 보정 셀은 prior 대신 학습된 `isotonic(로지스틱(C,L,F))`를 쓰고
> RR 필터를 우회한다(학습 승률 존중). **현재 자격 셀 0개 → 전부 prior.**

---

<a id="schema"></a>
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
  "candidates": [ { setup, dir, precond, entry, tp, sl, r_dist, rr, t_max, trail_dist?,
                    p_hat, p_source, C, L, F, confluence_n, veto[], size, fire } ],
  "meta": { ... legacy 대조용(학습 입력 아님) ... },
  "path": { n, o[], c[], h[], l[], complete, captured_at }   // 4h부터 증분, 72h 완성
}
```

**오프라인 파생 라벨**(`analysis/labels.py`):
`tb_win[setup]`(배리어 재생=승률 정답, `trail_dist` 실린 후보는 고정TP 대신 트레일링으로
재생) · `ret_Hh`/`exret_Hh`(BTC초과) · `mfe`/`mae` · `path_eff` · `class`(exret·데드존
기준 UP/FLAT/DOWN). **triple-barrier·exret이 1차 라벨**(베타둔감), 원시수익은 보조.

---

<a id="calibration"></a>
## 오프라인 보정 학습 — **부분풀링 (Phase 2, 그림자 운영)**

구(舊) 자격 게이트(탈중첩 독립표본 N≥100 × 거시 ≥2종)는 비현실적으로 높아 어떤 셀도
보정되지 못했다(실효≈0, 심장 정지). 이를 **계층적 부분풀링(partial pooling)** 으로 교체:

- **계층 수축**: GLOBAL→SETUP→BASE(setup×regime)→CELL. 셀 승률을 Beta-Binomial로 부모에
  수축(`(wr·n_indep + wr_parent·k)/(n_indep+k)`) → 자격 0/1 폐기, 표본 적어도 즉시 사용.
- **δ만 학습**: prior 기울기(wC/wL/wF) 고정, 셀 절편 오프셋 `δ_eff = clamp(conf·δ, ±cap)`만
  학습(소표본 과적합 차단). 라이브는 `P̂ = min(calib_cap, σ(prior_logodds + δ_eff))`.
- **그림자 운영**: `WRF_CALIB_DISABLED` 기본 `true` — 발사는 prior, 보정 P̂은 스냅샷에
  `p_cal`로 **기록만**. `analysis/backtest.py --ab`의 OOS Brier 우위 입증 후 `false` 전환.
- **주간 잡**(`.github/workflows/calibrate.yml`): 일요일 04:10 UTC, JSONL→δ_eff→
  `calibration_table.json` 커밋. 라이브는 이 산출물의 δ_eff만 읽는다(학습은 여기서만).

```bash
python analysis/calibrate.py --dry-run               # 셀별 수축·δ 요약(파일 미기록)
python analysis/backtest.py --ab                      # prior vs 보정 Brier·캘리브레이션
python analysis/situation_report.py --wrf             # 셀별 n·독립n·거시커버리지·승률
```

---

<a id="incubator"></a>
## 셋업 인큐베이터 운영 가이드

병목 진단(2026-07)의 결론: 신호 빈도의 근본 제약은 로직이 아니라 **표본 처리량**이다.
발사권 게이트(A-2)·부분풀링 보정은 이미 "검증된 것만 통과"를 자동 집행하는 폐루프를
갖췄지만, 셀당 결판이 쌓이지 않으면 그 무엇도 판정을 못 내리고 `live`(콜드스타트 기본)에
머문다. 이 절은 **BR이 이미 밟은 경로**(원트랙 승격 → 실측 미달 → 섀도 강등 → 재검증
대기)를 앞으로 **재사용 가능한 표준 절차**로 일반화한다 — 다음에 신규 셋업 후보가
생겼을 때, 혹은 BR을 재점등할 때 매번 같은 절차를 반복한다.

### 생애주기 4단계

```
① 섀도 입주        : 신규 디텍터를 WRF_SHADOW_SETUPS 에 추가한 채로 배포.
                      후보생성·JSONL 기록·오프라인 채점은 정상 동작, 라이브 발사만 0.
                      (5-G "새 셋업은 Phase 2 검증 후에만" 의 집행 — 논리만으로 켜지 않는다)
② 표본 축적(자동)   : calibrate.yml 이 매주 일요일 04:10 UTC 자동 실행.
                      JSONL → labels.candidate_dataset() → 셀별(setup×regime×macro)
                      그룹핑 → calibration_table.json 갱신·커밋. 사람 개입 없음.
③ 셀 판정(주간·사람) : python analysis/calibrate.py --dry-run 출력을 읽고 셀별
                      fire_rights 를 확인(아래 "판정 읽는 법" 참조). 자동 강등/복권은
                      코드가 하지만, "섀도 셋업 자체를 WRF_SHADOW_SETUPS 에서 뺄지"는
                      사람이 이 출력을 보고 결정한다(자동화된 임계값 없음 — 의도적).
④ 점진 점등 + 감시   : 판정 통과 셀만 살아 발사 시작. fire_rights 는 이후에도 계속
                      매주 재계산되어, 승률이 나빠지면 같은 셀이 자동으로 다시 섀도로
                      강등된다(히스테리시스 — 아래 표). 사람이 다시 끌 필요 없음.
```

### 판정 읽는 법 — 실제 데이터로 보는 예시

```bash
python analysis/calibrate.py --dry-run
```
출력 한 줄(BR 실측, 축약):
```
✅보정 BR|RANGING|CHOP: n=7 indep=2 wr=0.14→pool=0.31 발사결판=4 P(WR≥floor)=0.24 δ_eff=-0.11
```

| 필드 | 의미 |
|---|---|
| `n=7` | 이 셀의 결판(WIN/LOSS) 후보 수(명목) |
| `indep=2` | 그 중 **독립표본**(`WRF_INDEP_STRIDE_H=24h` 간격 탈중첩) — 명목보다 항상 작거나 같다 |
| `wr=0.14→pool=0.31` | 관측승률 → Beta-Binomial로 부모(SETUP 평균)에 수축시킨 승률(표본 적을수록 부모 쪽으로 당겨짐) |
| `발사결판=4` | 발사됐거나 "격리만 아니었으면 발사"였을 후보 수 — floor가 거부한 후보는 제외(발사분 승률만 제약) |
| `P(WR≥floor)=0.24` | 이 셀의 진짜 승률이 floor(0.58) 이상일 **사후확률**(Beta 사후분포). fire_rights 판정의 유일한 근거 |

**자동 판정 기준**(`config.py` 의 `WRF_FR_*`, 이미 main 반영):

| 전이 | 조건 | 의미 |
|---|---|---|
| `live → shadow` (강등) | `n_fire_decided ≥ WRF_FR_MIN_DECIDED(8)` ∧ `P(WR≥floor) < WRF_FR_DEMOTE_P(0.15)` | 발사결판 8건 이상 쌓였는데 승률이 명백히 floor 미달로 판명 |
| `shadow → live` (복권) | `P(WR≥floor) ≥ WRF_FR_PROMOTE_P(0.50)` | 결판수 요건 없음 — 섀도는 계속 표본이 쌓이므로 증거가 쌓이는 즉시 복권 |

비대칭(강등 0.15 vs 복권 0.50)의 근거는 손실 비대칭이다: 오발사는 실손 R이 영구히
남지만, 오강등은 기회비용 일시(섀도 상태에서도 표본·채점은 계속되므로 증거가 쌓이면
자동 복권된다). 위 BR 예시처럼 `발사결판=4 < 8` 이면 애초에 강등 판정 자체가
**발동을 안 하고 `live` 유지**로 방치된다는 점이 중요하다 — "안 나쁘다고 증명됨"이
아니라 "판정 보류"다. 표본이 8건을 넘기 전까지는 셋업 레벨 차단(`WRF_SHADOW_SETUPS`)이
유일한 안전장치라는 뜻이므로, 표본이 부족한 동안은 셋업 레벨 차단을 섣불리 풀지 않는다.

**셀 단위 판정과 셋업 단위 스위치는 이중 구조**임을 유의: `fire_rights`(위 표)는
셀(setup×regime×macro) 단위로 자동 작동하지만, `WRF_SHADOW_SETUPS`에서 셋업 이름
자체를 빼는 것은 **사람이 결정하는 상위 스위치**다. 방금 계산한 예시들처럼 결판이
8건에 못 미친 셀이 섞여 있는 상태로 상위 스위치를 풀면, "아직 증명 안 된" 셀까지
한꺼번에 `live` 콜드스타트로 노출된다 — 그래서 상위 스위치 해제는 "해당 셋업의
셀 대다수가 결판 8건을 넘기고 승격/강등 판정이 실제로 내려진 뒤"로 미룬다.

### 새 셋업을 인큐베이터에 넣는 절차 (재사용 체크리스트)

1. **디텍터 작성**: `detectors.py`에 `_detect_<NAME>` 추가. 기존 4셋업(TF/BO/MR/RV)의
   C/L/F 축 헬퍼(`_ctx_align`/`_flow_align`/`_ctx_exhaustion`/`_flow_exhaustion`)를
   재사용해 롱/숏 완전 대칭으로 작성한다(5-D). 새 절대임계 추가 금지(5-C) — 반드시
   백분위(`pct.pct_rank`) 경유.
2. **prior 등록**: `config.py`의 `WRF_PRIOR_B0`·`WRF_TMAX`에 신규 셋업 키 추가. b0는
   기존 4셋업의 base-rate 스펙트럼(TF -0.15 ~ RV -0.95) 안에서 보수적으로.
3. **섀도 등록**: `WRF_SHADOW_SETUPS`에 이름 추가(기본값에 포함해 커밋 — env 오버라이드
   에 의존하지 않는다). `detect_all()`의 실행 순서 튜플에 추가.
4. **Notion 스키마**: `notion_wrf.py`의 `_SETUP_OPTS`에 이름 추가(select 옵션만 — 스키마
   자동 self-heal이 나머지 처리).
5. **README 등록**: 이 절의 표에 진행상황 행 추가(아래 "현재 인큐베이터 현황").
6. **2주+ 대기**: ②표본 축적을 그냥 흘려보낸다. 코드로 할 일 없음.
7. **③④ 절차 그대로 적용**: 위 생애주기를 그대로 밟는다. 새 절차를 따로 만들지 않는다.

### 현재 인큐베이터 현황

| 셋업 | 상태 | 비고 |
|---|---|---|
| **BR**(밴드반전) | 섀도(`WRF_SHADOW_SETUPS="BR"`), 결판 최대 4건/셀 — 판정 보류 | 실측 승률 34.5%(floor 미달)로 재강등된 이력(Phase A 참조). 재점등엔 반전캔들 확인 게이트 강화(`WRF_BR_REQUIRE_REV_CANDLE`) + 신규 셀 콜드스타트 섀도 디폴트가 설계돼 있으나 **별도 PR 대기 중**(아직 main 미반영) |
| **TC**(추세지속·채널라이드) | **설계·구현 완료, 별도 PR 대기 중** — 아직 main에 없음 | TF의 눌림밴드에도 깊은피보에도 안 걸리는 채널추세(얕은 플래그 연속) 포착용 신규 디텍터. TF와 `loc_ema20` 밴드로 상호배타 |
| 부결 사유 계측(⑥) | **설계만, 미구현** | 디텍터별 최초 탈락 게이트를 스냅샷에 기록해 무후보 시간의 원인을 groupby로 바로 보이게 하는 관측성 개선. 코드 없음 |

이 표는 살아있는 문서다 — 셋업이 섀도→라이브로 넘어가거나 새 후보가 입주하면 이
표만 갱신하고, 위 4단계 생애주기 서술은 건드리지 않는다.

---

<a id="ops"></a>
## 운영 / 워크플로우

| 워크플로우 | 스케줄 | 역할 |
|------------|--------|------|
| `signal_1h.yml` | 매시 :05 | 수집→측정→엔진(L0~L4)→발사(페이퍼)→스냅샷 적재→Notion 미러 |
| `scoring.yml` | 매 :*/15 | 성숙 경로 채움 + triple-barrier 신호판정 + 스냅샷 라벨 백필 |
| `calibrate.yml` | 매주 일 04:10 | [Phase 2] JSONL→부분풀링 δ_eff 학습→`calibration_table.json` 커밋(그림자) |

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
python analysis/situation_report.py --wrf    # 셀 진단(오프라인 연구용)
python analysis/routing_scorecard.py         # 레짐 라우팅-유틸리티 진단(추종vs반전 실현R·ADX AUC)

# [Phase 1] 백테스트/리플레이 하니스 — 저장된 72h 경로로 현 prior 성능 측정
python analysis/backtest.py                   # 전체+setup별 성능 + 게이트 퍼널
python analysis/backtest.py --by setup_macro  # setup×거시별 실현승률·기대R·PF·MaxDD
python analysis/backtest.py --fired-only      # 발사 후보만(실거래 근사)
python analysis/backtest.py --funnel          # 빈도 병목(veto/floor/RR) 퍼널
python analysis/situation_report.py --perf --perf-by cell   # 동일 하니스 위임

# [Phase 2] 부분풀링 보정(학습) + A/B 그림자 평가(Gate-Out 계측)
python analysis/calibrate.py                  # JSONL→셀별 δ_eff 학습→calibration_table.json
python analysis/calibrate.py --dry-run        # 파일 쓰지 않고 셀별 수축·δ 요약만
python analysis/backtest.py --ab              # prior vs 보정 P̂ Brier·캘리브레이션 비교

# [P0/P1/P2] 반전랠리 병목 3처방 단일변수 A/B (2026-07)
python analysis/audit/verify_p012.py          # BR섀도 포함/반사실 · fast-struct · 트레일링 vs 고정TP
```

---

<a id="toggles"></a>
## 토글 레퍼런스 (ON/OFF 전체 일람)

모든 `WRF_*` 토글은 되돌리기 가능(env override)하고, 기본값은 `src/config.py`가 유일한
출처다. 여기 표는 그 스냅샷 — 값이 바뀌면 코드가 먼저고 이 표는 뒤따른다.
**근거** 열은 [실험 로그](#changelog)의 해당 항목으로 연결된다(같은 태그로 검색).

### 기본 ON (라이브 반영 중)

| 그룹 | 토글 | 효과 | 근거 |
|---|---|---|---|
| 레짐/라우팅 | `WRF_REGIME_ROUTING` | 강확정 추세에서 역추세 반전 억제 + TF 라우팅 복원(ADX 지연 보강) | Pillar1 |
| 레짐/라우팅 | `WRF_ROUTING_SELF_STRUCT` | 라우팅을 BTC매크로 종속 대신 심볼 자체 EMA구조로(알트 FN↓) | Pillar1 |
| 레짐/라우팅 | `WRF_REGIME_ER_TREND` | 효율비(ER)로 ADX가 놓친 방향성 추세 TRENDING 승격 | grind-fix |
| 레짐/라우팅 | `WRF_REGIME_ER_PCTL` | ER 승격을 절대임계 대신 코인 자기분포 백분위로 | Pillar1 |
| 레짐/라우팅 | `WRF_REGIME_SLOPE_PERSIST` | 느린 단일방향 grind를 방향지속(기울기+드리프트)으로 승격 | Pillar1 |
| 레짐/라우팅 | `WRF_BO_IN_RANGING` | RANGING에서도 박스돌파(BO) 허용(강게이트로 통제) | 연결결함#1 |
| 레짐/라우팅 | `WRF_RV_MACRO_EXEMPT` | RV(전환)만 거시정면충돌 하드베토 면제(구조붕괴 증거로 대체) | 연결결함#2 |
| 반전 C축 | `WRF_REV_IMPULSE_KILL` | 신선 임펄스(극단스트레치+단기구조 생존) 페이드 금지 | Phase C-v4 |
| 반전 C축 | `WRF_REV_RECLAIM_KILL` (+`WRF_REV_RECLAIM_MIN`=2) | 신선 리클레임(구조플립+VWAP+EMA ≥2) 페이드 금지 — impulse_kill보다 조기 발동 | **P0** |
| 반전 C축 | `WRF_REV_CTX_V2` | 반전 C를 macro-echo 포화 대신 심볼-로컬 구조정합으로(공백 A: 바닥반전 FN 해소) | **C축 V5 실험**(2026-07 라이브) |
| 추종 C축 | `WRF_CTX_RECLAIM_BOOST` (+`WRF_RECLAIM_FRESH_K`=6) | 추종 C에 리클레임 부스트 max-클램프 — P0 킬의 쌍대(공백 B: Phase3 추종 FN 회복) | **C축 V5 실험**(2026-07 라이브) |
| 반전 C축 | `WRF_D_SHADOW` | BR(밴드반전) 디텍터 가동(후보생성) — 발사권은 별도(`WRF_SHADOW_SETUPS`) | 밴드반전 일원화 |
| 반전 C축 | `WRF_D_REQUIRE_REENTRY` | BR 무장을 밴드터치가 아닌 '밴드복귀(재진입)'로 요구(밴드라이딩 오탐 방지) | 밴드반전 일원화 |
| 추종 C축 | `WRF_CTX_FAST_STRUCT` (+`WRF_CTX_FAST_W`=0.20) | 추종 C의 후행 macro 가중 일부를 자기 1H 빠른구조로 이관 | **P1** |
| 추종 C축 | `WRF_TF_FIB_PULLBACK` | TF 눌림 판정에 4H 피보 깊은눌림(50~61.8%) 경로 추가 | A1 |
| precond 완화 | `WRF_RV_SOFT_PRECOND` | RV 5중 AND를 소프트 스코어로(안전최소치만 게이트, 나머지는 L 감쇠) | Pillar2 |
| precond 완화 | `WRF_RV_REQUIRE_CHOCH` / `WRF_RV_REQUIRE_RETEST` | RV 하드모드 요구조건(soft=true면 사실상 L감쇠로 대체) | A4/G6 |
| 축 대칭성 | `WRF_PCT_MIDRANK` | 백분위 동점처리 완전 대칭(+1/(2n) 편향 제거) | Pillar4 |
| 축 대칭성 | `WRF_TF_MACD_SYM` | TF 모멘텀 재정렬을 롱/숏 대칭 요구(숏도 명시적 약세) | Pillar4 |
| 축 대칭성 | `WRF_RV_SIDED_SIGNALS` | RV 청산/키레벨거부를 진입방향에 맞는 쪽만 카운트 | Pillar4 |
| min-axis/EV | `WRF_PRIOR_MIN_AXIS_SOFT` | min-axis 하드절벽을 연속 페널티로(근거리 회복, 역행축은 강차단) | Pillar3 |
| min-axis/EV | `WRF_EV_GATE` (+`WRF_EV_RR_FLOOR`=0.85) | 고정 RR 대신 기대값(EV=P̂·RR−(1−P̂)≥0.15) 결합 게이트 | Pillar3 |
| SL/레벨 | `WRF_BO_SL_NEAR` | BO SL을 박스반대편 대신 돌파경계 근처로(RR 정상화) | grind-fix |
| SL/레벨 | `WRF_TF_TRAIL` (+`WRF_TF_TRAIL_ATR`=3.0·`WRF_TF_TRAIL_TMAX`=72) | TF 고정TP 대신 HWM∓ATR 무상태 트레일링 | **P2** |
| 계측 | `WRF_SHADOW_BAND` | 플로어 근접 미발사 후보(near-miss)를 기록만(표본기근 클래스 계측) | Phase 1 |
| 계측 | `WRF_RESEARCH_BARS` | 스냅샷에 백워드 1H 봉 N개 동봉 기록(오프라인 재현용) | — |

### 기본 OFF (섀도/미검증 — 데이터 근거로 명시적 강등)

| 토글 | 효과 | 근거 / OFF 사유 |
|---|---|---|
| `WRF_BR_REQUIRE_REV_VOL` / `WRF_BR_REQUIRE_REV_CANDLE` | BR precond에 TF/MR/RV와 동일한 반전봉 거래량·반전캔들 게이트 재사용 배선 | 과거 BR 후보 31건 전량이 이 게이트로 걸러짐(거래량 100%·반전캔들 필드 자체 부재) — 승률 재검증이 현재로선 불가, ON 후 신규 섀도 표본 축적 필요 ([BR정합](#changelog)) |
| `WRF_REGIME_ADX_SOLE` | ADX 단독으로 TRENDING 승격(구동작 복귀 스위치) | 후행 ADX 스파이크는 소진/반전 직전 신호라 추종 라우팅에 음(−)스킬 확인(AUC 0.45) — 강등 유지 (Pillar1) |

> **참고**: `WRF_REV_CTX_V2`·`WRF_CTX_RECLAIM_BOOST`는 2026-07-04 C축 V5 실험으로
> **기본 ON으로 전환**(위 "기본 ON" 표 참조). 사전등록 게이트(UPLEG 다레짐·B1 결판≥8)는
> 여전히 미충족이나, 백테스트가 악화를 보인 게 아니라 표본부족이라 사용자 지시로
> 실측 표본 축적을 위한 조건부 라이브 실험으로 전환. 되돌리기: 각 토글 `=false`.

### 거버넌스 스위치 (그림자 운영 · 발사권)

일반 기능 토글과 달리 **하위 시스템 전체를 여닫는** 스위치. true/false의 의미가 토글마다 달라 별도 표기.

| 스위치 | 기본값 | 의미 | 되돌리기 |
|---|---|---|---|
| `WRF_CALIB_DISABLED` | `true` | **true = 보정 비활성** — 발사는 prior 사용, 보정 P̂은 그림자 기록만 | `false` = OOS Brier 우위 입증 후 보정 P̂으로 발사 전환 |
| `WRF_SHADOW_SETUPS` | `{"BR","TC"}` | 목록의 셋업은 후보생성·기록만, 라이브 발사는 안 함 | `""`(빈 문자열) = 전부 라이브 |
| `WRF_FIRE_RIGHTS_ENABLED` | `true` | 셀별 사후검정 강등(`quarantine=FIRE_RIGHTS`) 게이트 작동 | `false` = 게이트 없이 구동작(전 셀 발사권 유지) |

### 표본처리량·정합 개선 (2026-07 · ②③④⑤)

병목 원인이 로직이 아니라 **표본 처리량**이라는 진단에 따른 4개 토글. 모두 되돌리기 가능.

| 토글 | 기본값 | 효과 | 되돌리기 |
|---|---|---|---|
| `WRF_CALIB_CAP_CONF_MIN` | 0.50 | **②캡 비대칭 수리** — 셀 신뢰도 conf<0.5면 보정캡을 prior캡(0.65)로 강등(소표본 과신 차단) | 0 = 항상 0.72 캡 |
| `WRF_LEDGER_SCRATCH_EXPIRED` | `true` | **③원장-보정 정합** — 만기청산을 원장에서 `SCRATCH`로 분류(보정 tb_win=None과 일치) | `false` = 만기도 손익부호 WIN/LOSS(구동작) |
| `WRF_TRIG_WINDOW` | 0 | **④트리거 시간창** — 반전캔들을 '최근 N개 완성봉'까지 인정(점사건↔상태 정렬 소멸 완화) | 0 = 현재봉만(구동작) |
| `WRF_TC_ENABLED` | `true` | **⑤셋업 인큐베이터** — TC(추세지속·채널라이드) 섀도 셋업 후보생성(발사는 `WRF_SHADOW_SETUPS`가 차단) | `false` = TC 후보 미생성 |

### 레벨/구조 파라미터 (되돌리기 값 존재)

단순 ON/OFF가 아니라 수치 하나로 "무효과 값"이 정의된 파라미터.

| 파라미터 | 기본값 | 효과 | 되돌리기(무효과) 값 |
|---|---|---|---|
| `WRF_SL_ATR_CUSHION` | 1.5 | TF/RV 구조SL ATR쿠션 배수 | 0 |
| `WRF_REV_VOL_MULT` | 1.0 | 반전봉 거래량 게이트 배수 | 0 |
| `WRF_BO_FUND_BONUS` | 0.15 | BO 펀딩 컨트래리언 L 가점 | 0 |
| `WRF_TF_LATE_MATURITY_MULT` | 0.85 | 성숙추세 TF L 감쇠 | 1.0 |
| `WRF_CONFLUENCE_L_BONUS` | 0.05 | 컨플루언스 중첩 L 가점 | 0 |
| `WRF_MR_TP_TARGET` | `"mid"` | MR TP 목표(중심선) | `"opposite"`(반대편 경계) |

### 실질 튜닝 파라미터 (3~5개 원칙, 단일변수·워크포워드만)

- `WRF_PCT_WINDOW`(백분위 윈도) · `WRF_PCT_EXTREME_HI/LO`(극단컷, MR RSI 극단 구동) ·
  `WRF_WIN_FLOOR`(승률 플로어) · `WRF_CELL_N_MIN`(신뢰게이트).
- 위 외 모든 수치 상수(VETO 임계·계층수축 k값·사이징 배수 등)는 엔진 상수이지 튜닝
  대상이 아니다 — 바꾸려면 워크포워드 검증부터.

---

<a id="symbols"></a>
## 심볼 / 시크릿

- **심볼**: `BTC/USDT ETH/USDT HYPE/USDT` (확장: SOL/SUI/XRP)
- **Secrets**: `OKX_API_KEY/SECRET/PASSPHRASE`, `TELEGRAM_BOT_TOKEN/CHAT_ID`,
  `NOTION_TOKEN`, `NOTION_SIGNALS_DB_ID` / `NOTION_SNAPSHOTS_DB_ID`(또는
  `NOTION_PARENT_PAGE_ID`로 자동 생성)
- **Variable**: `ALERT_ENABLED`, `WRF_*` 파라미터 오버라이드 — 전체 목록은
  [토글 레퍼런스](#toggles) 참조.

---

<a id="notion"></a>
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

<a id="structure"></a>
## 프로젝트 구조

```
sig-bot-1H/
├── .github/workflows/{signal_1h,scoring,calibrate}.yml  # calibrate=Phase2 부분풀링(그림자)
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
│   ├── labels.py                # triple-barrier(+트레일링)·exret·class·candidate_dataset
│   ├── calibrate.py             # ★[Phase 2] 부분풀링 보정 잡(계층 수축→셀별 δ_eff)
│   ├── backtest.py              # ★[Phase 1] 백테스트/리플레이 하니스(성능+퍼널)
│   ├── situation_report.py      # 상황·WRF 셀 진단(+ --perf 하니스 위임)
│   ├── routing_scorecard.py     # 레짐 라우팅-유틸리티 스코어카드(추종vs반전 실현R·오프라인 측정)
│   └── audit/verify_p012.py     # [P0/P1/P2] 단일변수 A/B(BR섀도 반사실 포함)
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

<a id="changelog"></a>
## 실험 로그 (히스토리)

날짜순 변경 이력. 각 항목은 진단→처방→백테스트 검증까지의 전체 기록이며,
기본 접힘 상태다(가장 최근·진행 중인 실험만 펼쳐져 있다). [토글 레퍼런스](#toggles)의
**근거** 열이 여기 제목과 매칭된다.

<details open>
<summary><b>[반전봉 완성봉 정렬] rev_vol_ratio·반전캔들 미완성 형성봉 참조 버그 수리 — 반전 계통 FN 근본원인 (2026-07-07)</b></summary>

**증상(제보)**: BTC/USDT 2026-07-06 급락(→61,283) 후 V자 반등이라는 교과서적 반전 롱
자리에서 **후보 0건**. 스냅샷 확인: 플러시 바닥(07/06 22:00 KST) BB %b=−0.09·RSI=26.7·
거래량 5.5배·되돌림 optimal — MR/RV 롱 전제가 다 갖춰졌는데 후보가 안 생김.

**근본원인**: 반전봉 거래량비 `rev_vol_ratio`(`features.py`)가 분자로 **미완성 형성봉
`iloc[-1]`** 을 썼다. 잡은 매시 :05에 도는데 `data_pipeline`은 형성봉을 버리지 않으므로
`iloc[-1]`은 몇 분치 거래량만 누적된 봉 — 완성봉(분모) 대비 구조적으로 ≈5/60로 짓눌린다.
실측 전 스냅샷 1,379행: **rev_vol_ratio 평균 0.111, ≥1.0 단 0.4%**(vol_ratio는 평균 0.98로
정상). 이 값이 `_rev_vol_ok`(≥1.0) 게이트에 걸리는데, 그 게이트가 **TF·MR·RV 세 반전
셋업의 하드 precond** → 반전 후보가 C/L/F·floor에 닿기도 전에 99.6% 상시 사살. 유일하게
살아남던 후보(07/07 00:00 Candidates=1)는 `_rev_vol_ok`가 **없는 유일한 셋업 BR**이며,
BR은 섀도 격리라 발사 0. (이전 [BR 재진단](#changelog)이 "BR 31건 전량 rev_vol<1.0"을
BR 저품질 증거로 해석했으나, 실제로는 이 형성봉 버그의 전-셋업 공통 아티팩트였다 — 오진 정정.)

**처방(외과적·A안)**: 반전봉 거래량과 반전캔들이 **동일한 '완성'봉을 보게 정렬**.
- `features.py`: `rev_vol_ratio` 분자를 `iloc[-2]`(마지막 완성봉), 분모를 그 직전 N봉으로
  이동 — `vol_ratio`(BO용)와 같은 완성봉 규약. 사과-대-사과 비교 복구.
- `analysis_engine.analyze_candle_pattern`: `offset` 인자 추가(기본 0=기존 동작 보존).
  **1H 호출만 `offset=1`**(형성봉 절단→완성봉 핀/인걸핑) — 4H/1D는 불변, WRF는 1H 캔들만
  소비하므로 블라스트 반경을 1H로 한정.

**FP 통제**: 게이트를 느슨하게 한 게 아니라 *의도대로 작동*시킴. 무거래량 나이프캐칭은
여전히 차단(대량이라도 완성봉이 강세 반전캔들이 아니면 롱 후보 미생성). C축 킬(리클레임·
임펄스)·min-axis·EV·floor 방어선 불변. 새 튜닝노브 0개(되돌리기는 기존 `WRF_REV_VOL_MULT=0`).

**검증**(`scratchpad/verify_revvol_fix.py`, 합성 결정적): ①완성봉 offset=1이 강세 인걸핑
포착·형성봉 offset=0은 미포착 ②구 rev_vol=0.06(탈락)→신 3.5(통과) ③형성봉 거래량
40~600 스윕에도 구는 상시 탈락·신은 안정 통과 ④대량 '음봉' 완성봉은 반전캔들 미포착(FP
불변) — 4항 전부 PASS. 하위호환(기존 무-offset 호출)·짧은 df 가드·전 모듈 컴파일 확인.
</details>

<details>
<summary><b>[C축 V5 실전실험] 반전C=v2 + 추종 리클레임부스트 라이브 점등 — FN 최소화 (2026-07-04, 기본 ON)</b></summary>

C축 V5 설계·골격(아래 [Phase C-V5] 항목)을 이전 테스트 결과로 정교화한 뒤 사용자
지시로 **실전 라이브 실험 점등**. 목표는 **FN(놓친 발사) 최소화**. 반전 국면 4단계의
두 FN 공백을 동시에 겨냥한다: **공백 A(Phase 2 바닥반전 FN)** = 반전C `WRF_REV_CTX_V2`,
**공백 B(Phase 3 추종 FN)** = 추종 리클레임부스트 `WRF_CTX_RECLAIM_BOOST`.

**정교화 — 데이터 기반 선택(새 튜닝노브 0개, 5-J/5-K 준수)**:
- **반전 C: v5lite 기각 → v2 채택.** 3-way 재생(`verify_caxis_v5.py`)에서 v5lite(반전 C에
  1H fast만 주입) IC **0.038** < v1 0.054 < v2 **0.095** — fast 단독 주입은 순위판별을
  오히려 훼손. v2(심볼-로컬 구조 주입)가 우세. `verify_br_caxis.py` 재실행(★기존
  스크립트가 `_ctx_exhaustion` 인자 누락으로 실행 불가였던 버그 수정 후): 사전등록 4기준
  전부 통과(IC 0.082→0.215·win% 33.3→36.4·exp_R 0.147→0.157·발사빈도 유지).
- **부스트 지각조건: macro-only 기각 → slow-lag 유지.** "매크로 태그만 지각" 조건은
  새 발사 **0건**(과엄격·자기FN) — 승리 발사 5건은 btc_macro는 CHOP이지만 심볼 자체
  4H/일봉 구조가 여전히 약세인 "심볼-로컬 지각"이라, 전체 slow 블렌드(<0)로 조건화해야
  잡힌다. K(신선도 윈도) 민감도 무(4~18 동일 5발사) → 기본 6 유지(샘플튜닝 금지).

**백테스트(배포상태, `verify_caxis_v5.py`·`verify_br_caxis.py` 재현 가능)**:
- **V5-B 부스트**: 새로 열린 추종 발사 5건(전부 롱·grind 표본), 결판 3/3승(exp_R +1.178)
  — **직접적 FN 회복**. 사전등록 B1(결판≥8)은 미달이나 **악화 신호 0**(무손실 개방).
- **V2**: downleg 표본에서 반전 발사 6→2로 감소하나 이는 knife-catch 롱 FP 제거이고
  (v1 롱 5→v2 0, 승자 숏 +1), **FN을 늘리지 않음**(승리 발사 손실 0). 설계 목적인 바닥반전
  FN 해소는 UPLEG/전환에서 발현 — 실험기간 다레짐 표본으로 감시.
- **합성 시나리오**(`verify_caxis_v5_synthetic.py`, 상승/하락/횡보/전환): 배포 기본값(둘 다
  ON)에서 롱/숏 완전대칭(24,000+ 케이스)·무상태·무크래시 전부 PASS.

**왜 게이트 미달인데 점등하나(정직한 기록)**: 표준 5-I라면 B1·G2(UPLEG) 미충족으로 OFF가
맞다. 그러나 (a)백테스트가 **악화가 아니라 표본부족**만 보였고 (b)둘 다 FN을 직접 회복하며
(c)사용자가 "실험기간 실측 표본 축적"을 명시 지시 — P0/P1/P2 선례와 동일한 조건부 라이브
실험이다. **모니터링**: `verify_caxis_v5.py`를 정기 재실행해 실제 발사분 실현 win%·PF를
추적, 악화 관측 시 즉시 `WRF_REV_CTX_V2=false`/`WRF_CTX_RECLAIM_BOOST=false`로 원복(전부
되돌리기 가능). 점등 확정 게이트는 불변: G2(UPLEG≥300·결판≥20) ∧ B1(결판≥8) 전부 PASS.

</details>

<details>
<summary><b>[BR정합] BR precond 구조결함 진단 + 계측·게이트 준비 (2026-07-04, 기본 OFF)</b></summary>

BR(밴드반전) 섀도강등 재확인 요청에서 출발한 근본원인 재진단. 기존 `verify_br_caxis.py`가
**`_ctx_exhaustion()` 호출에 `pcts` 인자가 누락돼 처음부터 `TypeError`만 내던 버그**(git
이력상 이 파일은 최초 커밋 이후 수정된 적이 없어 — 한 번도 실행된 적 없는 스크립트였다)를
발견·수정. 재실행 결과 기존 README에 적혀 있던 수치(win% 28.6%/25.0%)보다 **더 나쁜
수치**로 정정됨: v1 C축 win%=20.0%(결판15), v2 C축 win%=22.2%(결판9) — **C축 버전과
무관하게 floor 58%에 한참 못 미침**(BR을 라이브로 되살리는 최종 판정 = 섀도 유지, 재확정).

**근본원인 재진단**(`analysis/audit/probe_br_precond.py`): BR은 TF/MR/RV가 전부 쓰는
반전봉 거래량 게이트(`_rev_vol_ok`)가 유일하게 빠져 있고 반전캔들 요구도 없다 — 무장
조건이 "밴드 재진입 1개"뿐이다. 실측: **저장 BR 후보 31건 전량이 `rev_vol_ratio<1.0`**
(거래량 게이트를 소급 적용하면 100% 탈락) — "밴드 재진입"이라는 트리거가 저확신·저거래량
드리프트를 잡고 있다는 구조적 증거. 방향별로도 숏 win%=13.3%(n=15) vs 롱 33.3%(n=6)로
극단적 비대칭이 관측되나, 미러 속성 테스트(아래 Part 1b)로 **코드 자체의 롱/숏 대칭은
이미 증명**돼 있어 이는 버그가 아니라 "단일레짐(하락장)에서 숏 트리거가 압도적으로 많이
발생하되 대부분이 되돌림 잡음"이라는 시장구조 신호로 해석된다.

> **[2026-07-07 정정]** 여기서 "BR 31건 전량 `rev_vol_ratio<1.0`"을 BR 트리거의 저품질
> 근거로 본 해석은 오진이었다. `rev_vol_ratio`는 미완성 형성봉(`iloc[-1]`)을 분자로 써
> **모든 셋업에서 상시 <1.0**(전 스냅샷 평균 0.111)이었다 — BR 고유 신호가 아니라 전-셋업
> 공통 버그. 완성봉 정렬로 수리(위 [반전봉 완성봉 정렬](#changelog) 항목). BR 자체의 섀도
> 유지 판정(win% floor 미달)은 이 버그와 무관하게 유효.

- **계측 선행**(`raw["rev_candle"]`, 무토글): MR/RV가 precond에 쓰는 반전캔들 판정
  (bullish/bearish pin·engulf)을 raw에 영구 박제(schema는 raw 전체를 그대로 저장하므로
  스키마 변경 불요) — 지금부터 BR 정합성 가설이 검증 가능한 표본으로 쌓인다.
- **`WRF_BR_REQUIRE_REV_VOL`·`WRF_BR_REQUIRE_REV_CANDLE`**(둘 다 **기본 OFF**): BR
  precond에 TF/MR/RV와 동일한 게이트를 재사용 배선만 해둠 — 새 로직 발명이 아니라 이미
  검증된 기존 패턴의 이식. **OFF인 이유**: 과거 표본 31건 전량이 이 게이트로 걸러져(거래량
  100%, 반전캔들은 필드 자체가 과거 데이터에 없어 100%) 승률 재검증이 현재로선 원천
  불가능 — ON 후 축적되는 신규 섀도 표본으로만 판정 가능(5-I). BR은 `WRF_SHADOW_SETUPS`로
  라이브 발사가 이미 막혀 있어 ON으로 바꿔도 안전(후보 생성 감소만 발생, 발사권과 무관).
- **검증**: 미러 속성 테스트(`verify_caxis_v5_synthetic.py` Part 1b) 500표본×4토글조합 —
  신규 게이트가 5-D(롱/숏 완전대칭)를 만족함을 확인. `verify_p012`·`verify_br_caxis`
  재실행으로 기본값 OFF 상태에서 기존 수치가 완전히 무회귀임을 확인.
- **미결**: 거래량 게이트가 역사표본을 100% 걸러낸다는 사실 자체가 우려 지점이다 — 밴드
  재진입(평균회귀) 이벤트는 본래 조용한 드리프트라 TF/BO 같은 폭발성 반전과 같은 거래량
  기준(`WRF_REV_VOL_MULT`=1.0)을 요구하는 게 맞는지, 아니면 BR 전용의 더 낮은 상대 기준이
  필요한지는 신규 표본 축적 후 재검토 대상(파라미터 신설은 5-K 예산 내에서 판단).

</details>

<details>
<summary><b>[Phase C-V5] C축 V5 — 설계 + 공유커널 + 리클레임 부스트 골격 (2026-07-04, 기본 OFF)</b></summary>

C축 차세대 설계. 전체 설계·후보 비교·예비 실측은 **docs/CAXIS_V5_DESIGN.md** 참조.
핵심 프레임: 반전 국면 4단계 중 **Phase 2(바닥 형성) 반전 FN**과 **Phase 3(리클레임
후) 추종 사각지대**가 남은 공백이며, 특히 후자는 P0 킬이 소비하는 리클레임 증거의
반쪽("추종 진입은 유효해졌다")이 버려지는 문제다(킬↔부스트 쌍대성 단절).

**예비 실측**(`analysis/audit/probe_caxis_v5.py`, 라벨-프리·방향분리): 리클레임 증거는
**상태로는 엣지 0**(+24h ~49% ≈ 베이스라인), **신선 플립 단독은 휩소 역엣지**(46~49%),
**"선행 반대레그 후 신선 플립" 이벤트만 양방향 대칭 개선**(+24h 롱 60.7%/숏 68.8%,
n=44 — 가설 생성용). 신선도 가중 블렌드 안(V5-D)은 이 실측으로 기각.

- **V5-0 공유 증거 커널**(`_struct_evidence`/`_slow_align`, 무토글): 추종 블렌드·부스트가
  같은 프리미티브를 한 곳에서 소비 — P1-미전파류 단절 재발 방지. **회귀: 저장 스냅샷
  2,450건(1,225행×양방향) C 비트 동일** 확인(동작 불변).
- **계측 선행**: `bars_since_vwap_flip`/`bars_since_ema20_flip`(부호플립 후 경과 봉,
  무상태 — features가 매 실행 재구성하는 dist 시계열에서 즉시 산출)을 raw에 기록만
  추가. 부스트 OFF여도 박제돼 향후 검증 표본이 쌓인다.
- **V5-B 리클레임 부스트**(`WRF_CTX_RECLAIM_BOOST`, **기본 OFF**): 추종(TF/BO) 전용
  max-클램프 — 진입방향 리클레임 완결(≥`WRF_REV_RECLAIM_MIN`, P0 임계 재사용) ∧
  VWAP/EMA20 플립 신선(≤`WRF_RECLAIM_FRESH_K`=6봉, 진입방향) ∧ 느린 구조(거시·4H·1D)
  아직 반대(지각 중)이면 C를 고정 수위(리클레임 2→+0.25, 3→+0.50)로만 끌어올림.
  가산 아님(5-J), 예측 아님(완결 사건 인식). **개방형(신규 발사 생성)이라 v4/P0의
  "닫기 전용=안전" 논리가 없음 → 사전등록 게이트 통과 전 점등 금지.**
- **V5-R(v2-lite, 반전 C에 1H fast만 주입)은 하니스-먼저 → 코드 미구현이 정답으로
  판명**: `verify_caxis_v5.py` 3-way 재생에서 v5lite IC 0.038 < v1 0.054 < v2 0.095 —
  fast 단독 주입은 순위판별을 오히려 훼손. v2가 반전 C 개선의 우세 후보로 유지
  (채택 게이트는 기존과 동일: UPLEG 다레짐).

**백테스트(`analysis/audit/verify_caxis_v5.py`, 사전등록 — 기준 변경 금지) 첫 실행**:
V5-B 부스트로 새로 열린 발사 5건(전부 롱·grind 표본), 결판 3건 3승(expR +1.178) —
**그러나 B1(결판 ≥8) 미달로 판정불가가 공식 결과**(성급 점등 금지). 라벨-프리 B5는
형식상 양방향 PASS(롱 51.0% vs 49.3% — 미미, 숏 86.2% vs 50.7% — **단일레짐 베타
가능성이 커 신뢰 금지**, n=29). G2(UPLEG≥300) 미충족으로 fade-방향 판정은 전부
판정불가 유지. **모니터링**: 스냅샷 축적 후 `verify_caxis_v5.py` 재실행 → B1~B5 전부
PASS 시에만 점등 논의. 되돌리기: 전부 `WRF_*` 토글(기본값 = 구동작).

</details>

<details open>
<summary><b>[P0/P1/P2] 반전랠리 병목 3처방 — 라이브 실험 (2026-07-04, 기본 ON)</b></summary>

**진단**(6/30~7/2 반전랠리, JSONL 실측): 후행 `btc_macro`(DOWNLEG)가 RV 숏 C축을 +1.0으로
포화시켜 상승랠리에 확신 숏이 발사(역행 스톱아웃=FP)되는 한편, 같은 후행 맥락이 돌파 롱
(L=+0.8로 위치는 최상)의 C를 −0.6까지 눌러 자가 억제(FN)했다. `analysis/audit/tune_regime.py`
실측: 1H 효율비/기울기 계열 판별자는 DIR−CHOP 분리력이 거의 0(추세시작을 사전예측 불가)
→ "예측 개선"이 아니라 "지각에 강건"한 처방으로 설계.

- **P0** `WRF_REV_RECLAIM_KILL`(+`WRF_REV_RECLAIM_MIN`=2): 페이드 대상 레그가 자기 1H
  구조로 신선하게 리클레임(구조플립+VWAP재탈환+EMA ≥N)하면 역추세 반전(MR/RV/BR) C 하드차단.
  `_impulse_kill`(스트레치·성숙 요구 → 지각)의 조기-구조 거울짝. 예측이 아니라 거부라서
  신호분리력이 불필요. 상승랠리 숏·하락임펄스 롱(칼받기) 대칭 차단.
- **P1** `WRF_CTX_FAST_STRUCT`(+`WRF_CTX_FAST_W`=0.20): 추종 C의 후행 macro 가중(0.45)을
  자기 1H 빠른구조(bos/choch/failed_break/ema/VWAP)로 일부 이관(가중합=1 보존·대칭).
- **P2** `WRF_TF_TRAIL`(+`WRF_TF_TRAIL_ATR`=3.0·`WRF_TF_TRAIL_TMAX`=72): TF에 한해 고정
  2.5R TP 대신 HWM∓k·ATR 무상태 트레일링. 신호시점 `trail_dist` 주석 발행 →
  `labels.triple_barrier(trail_frac=…)`가 동일 규칙으로 오프라인 채점(라이브 포지션 상태
  불필요, 5-E 준수).

**백테스트(`analysis/audit/verify_p012.py`, 단일변수·1195스냅샷·UPLEG 0건) 결과 — 솔직한
요약**: **셋 다 "확증"에 이르지 못했다.**
- P0: 현행 라이브(BR 섀도강등)에선 발사 **무변화(13→13)**. 이유가 결정적 — 문제의 랠리
  역추세 숏 4발은 이미 `split_band_reversal`로 `setup=BR` 재분류 → 섀도 강등돼 라이브
  발사집합 밖에 있었다(=BR 섀도가 이미 이 FP를 선차단 중, P0는 그 위에서 중복). BR 섀도를
  반사실로 해제하면 P0가 손절 1건만 순제거(승률 41.7→43.5%·PF 1.35→1.46·익절희생 0,
  단 n=1로 과신 금지).
- P1: **완전 무변화**(신규 발사 0). 0-UPLEG 하락장에선 fast-struct를 얹어도 추종 롱 C가
  floor 미달 — 이 데이터로는 검증 자체가 불가능하다.
- P2: TF 발사가 **2건**뿐이라 무결론(둘 다 트레일 발동 전 초기 SL에서 선청산).

**그럼에도 라이브 점등한 이유**: 표준 절차(5-I, 검증→점등)라면 위 결과로는 OFF 유지가
맞다. 그러나 이번엔 사용자가 "실험 중이니 켜서 실측 표본을 쌓자"고 명시적으로 지시했고,
백테스트가 **악화를 보여준 것도 아니다**(P0/P1은 순수 무변화, P2는 표본부족일 뿐 음성
신호 없음) — 그래서 사전 오프라인 게이트를 실거래 관찰로 대체하는 조건부 라이브 실험으로
전환했다. **모니터링**: `analysis/backtest.py --ab` · `analysis/audit/verify_p012.py`를
정기 재실행해 실제 발사분의 실현 승률·PF를 계속 추적하고, 악화가 관측되면 즉시
`false`로 원복한다(전부 되돌리기 가능한 `WRF_*` 토글).

</details>

<details>
<summary><b>[Phase C-v4] 임펄스-페이드 킬 — C축 개혁의 데이터 생존안 (기본 ON · 게이트 닫기 전용)</b></summary>

'7/3 BTC 롱 부재' 진단에서 출발한 반전형 C축 개혁 실험 4종의 결론
(`analysis/audit/verify_rev_ctx_reform.py`, 2026-06~07 후보 79건 반사실·사전등록):

| 변형 | 아이디어 | 발사 n | 실현 승률 | 평균R | 판정 |
|---|---|---|---|---|---|
| cur (v1 echo) | 현행 | 29 | 47.6% | +0.278 | 기준 |
| stretch | 바닥 롱 개방(과확장 백분위) | 51 | 46.5% (신규 롱 36%) | +0.315 | ❌ 기각 |
| v3 복합 | river+stretch+**decel(전환확인)** | 26 | 33.3% | −0.125 | ❌ 기각 |
| **v4 임펄스킬** | **신선 임펄스 페이드 금지** | 18 | **53.8%** | **+0.333** | ✅ 채택 |

- **게이트 열기는 전부 실패**: 1h 상태피처로는 캐피출레이션 내부의 바닥 타이밍이 분해
  불가(06-24 실측: 같은 loc 0.00에서 1시간 간격 WIN/LOSS 교차). decel류 전환확인은
  구조적으로 **후행** — 진짜 바닥은 차단하고 반등 후 추격만 산다(신규 롱 0/4 전패).
  또한 라이브가 미발사 후보 전량을 기록하고 오프라인이 반사실 채점하므로, **라이브 출혈로
  살 수 있는 정보가 없다**(원장이 공짜로 준다) — '출혈=수업료' 논리가 성립하지 않는 구조.
- **실측 출혈원은 반대쪽**: macro 태그가 전환을 수일 후행하는 동안 '이미 돌아선 시장'에
  대한 페이드(07-01~02 랠리 숏 결판 5건 전패)가 C=+0.25~+1.0 확신으로 발사되고 있었다.
- **v4 규칙**(양방향 대칭, `_impulse_kill`): 페이드 대상 레그가 자기분포 극단 스트레치
  (`loc_vwap` 백분위, |axis| ≥ `WRF_REV_IK_STRETCH`=0.6)이면서 심볼 자기 단기구조
  (1h EMA·MACD부호·BOS/CHoCH 중 ≥ `WRF_REV_IK_ALIVE`=2)상 살아있으면 **C=−0.5 강제**.
  새 발사 0(닫기 전용 — 출혈 없음). v1/v2 어느 베이스와도 합성 가능.
- **한계·감시**: 결판 표본 소수(제거집합 8건 중 승자 3건 동반 제거 — 사전등록 규칙을
  사후 미세조정하지 않은 대가). fire-rights 주간 사후검정이 계속 감시하며,
  `WRF_REV_IMPULSE_KILL=false`로 즉시 되돌리기 가능.

</details>

<details>
<summary><b>[Phase C] 반전형 C축 v2 — macro-echo 포화 해소 (기본 OFF · 과적합 경계)</b></summary>

앞선 진단의 근본원인 ②(반전형 C축이 재는 게 '소진'이 아니라 'BTC 매크로 태그 재확인')
교정. `_ctx_exhaustion`은 `btc_macro` 한 축만 써서 **DOWNLEG×숏이면 코인 자기상태와
무관하게 C=1.0으로 포화**(실측 고유값 3개: −0.5/0.25/1.0) → floor·사이징이 변별력을 잃고,
매크로 태그의 알트 예측력도 약함(ETH/HYPE는 DOWNLEG 태그 시 24h 낙폭이 CHOP보다 되레 작음).

- **v2 설계**: `_ctx_align`(추종형)과 공유하는 `_ctx_struct_align`(0.45·거시 + 0.25·바이어스 +
  0.20·4H추세 + 0.10·일봉EMA20/50)을 주입 — **macro 유효가중을 0.75→0.34로 낮추고 나머지를
  심볼 자체 구조로** 채운다. `C = base + (1−base)·정합`이라 **출력 envelope[−0.5,1.0]과
  극단(깨끗한정렬=+1·신선칼받기=−0.5)은 구설계와 비트 동일 — 중간 해상도만 추가**(구설계가
  맞았던 극단은 불변). 롱/숏은 부호 반전 대칭(5-D). 셀 키 불변(C축 연속피처, 5-H).
- **과적합 규율**: 가중치를 표본에 튜닝하지 않고 검증된 `_ctx_align` 값을 차용. 검증은
  독립 재구현으로 **방향만** — 고유값 3→10(포화 해소), IC old +0.13→v2 +0.20(시간분할
  전·후반 양 구간 일관), 의미론 비반전(HYPE류 'BTC-down·심볼-up' 숏이 +1.0→+0.175로 교정).
- **기본 OFF 이유**: 누적 데이터가 **DOWNLEG/CHOP 단일레짐**이라 fade '방향'의 통계 확증은
  UPLEG 관측 후에만 가능(5-I 검증→점등). IC·의미론은 방향 확인됐으나 점등은 사용자 판단
  또는 UPLEG 데이터 게이트. **점등**: `WRF_REV_CTX_V2=true`(즉시 되돌리기 가능).
- **백테스트 검증(`analysis/audit/verify_br_caxis.py`)**: v1 vs v2 A/B(반전 발사집합 재생).
  **v2가 IC(순위판별)는 개선**(0.283→0.346, 시간분할 양구간 일관)했으나 **발사분 실현
  성능은 악화**(win% 54.5→45.5·exp_R 0.592→0.357·Brier 소폭↑). 원인은 **단일레짐 교란** —
  v2가 낮춘 'BTC-down·심볼-up 숏'이 일방 하락장에선 시장베타로 이겨서, 옳은 de-prioritize가
  이 표본에선 손해로 보인다(양방향 시장이라야 판가름). 사전등록 4기준 중 2개(Brier·exp_R
  비열등) 미통과 → **OFF 유지 확정**. 점등 게이트 = UPLEG 포함 다레짐 재검증(과적합 회피상
  기준 완화 안 함).

</details>

<details>
<summary><b>[Phase A] BR 셋업 분리 + 발사권(fire-rights) 게이트 (2026-07)</b></summary>

2주 라이브 페이퍼(결판 23)·오프라인 리플레이(결판 55)·순수 가격데이터(1,001 스냅샷)의
**삼중 교차진단** 결과를 반영한 구조 교정. 예측 파라미터 추가 0개(과적합 무관 — 분류
교정 + 발사권 박탈/복권만).

- **진단**: ① 위 '원트랙 승격'은 섀도 실측 검증 없이 논리 근거만으로 이뤄져 5-I(검증→점등)
  위반이었고, 승격 후 밴드반전이 라이브 물량 95%를 차지하며 **실측 승률 40%**(floor 0.58
  미달, 순 R −1.1)로 판명. ② 밴드반전은 트리거(밴드복귀 1개)·경제성이 RV_proper(소진+
  반전캔들+확인≥2, 실측 6/6승)와 다른 **이질 모집단**인데 같은 `setup=RV` 셀에 섞여 보정이
  "둘의 평균"만 배울 수 있었다(편향 고착). ③ 목적함수 `max N s.t. WR≥floor`의 제약이
  ex-ante(P̂)로만 존재 — 셀의 실현 승률이 아무리 낮아도 발사권을 잃지 않는 **폐루프 부재**.
- **A-1 BR 분리**: `_detect_band_reversal` → `setup="BR"`. b0·T_max·레벨·거시베토 면제는
  RV와 동일하게 이관(분리=재분류, 동작 보존). 과거 JSONL은 `labels.split_band_reversal`이
  **소급 재분류** — 후보에 reason이 없어 무장조건(완성 직전봉 %b 밴드외곽→복귀)을 path
  복원 종가로 재유도(라이브 발화 26건 대조: 후보 기록된 21건 전부 일치·오류 0). 원본
  파일 불변(오프라인 메모리 재라벨). 엔진 dedup은 BR·RV를 같은 반전 패밀리로 묶어 유지.
- **A-2 발사권 게이트**: 주간 `calibrate.py`가 셀별 **'발사 ∪ 격리-미발사' 결판**의
  Beta-Binomial 사후분포로 `P(WR ≥ floor)`를 계산해 `fire_rights ∈ {live, shadow}` 발행
  (floor가 거부한 후보의 손실로 강등하지 않음 — 제약은 발사분 승률). 강등 셀 후보는
  `quarantine=[FIRE_RIGHTS]`로 기록만 되고 발사 안 됨. 히스테리시스 비대칭(강등 0.15 /
  복권 0.50) 근거 = 손실 비대칭: 오발사는 실손 R 영구, 오강등은 기회비용 일시(섀도로
  증거가 계속 쌓여 자동 복권). 라이브는 테이블의 이 필드만 읽는다(5-B 무손상).
- **BR 섀도 강등**: `WRF_SHADOW_SETUPS`(기본 `"BR"`)의 셋업은 `quarantine=[SHADOW_SETUP]`
  — 신규·미검증 셋업의 기본 상태(5-G "새 셋업은 보정 검증 후에만"의 집행). 셀별 발사권
  게이트가 표본 축적(셀당 발사결판 8+) 후 공식 판정을 내리면, 사람 심사를 거쳐 목록에서
  제거해 재점등한다. **되돌리기**: `WRF_SHADOW_SETUPS=""` + `WRF_FIRE_RIGHTS_ENABLED=false`
  = 구동작 완전 복귀.
- **백테스트 검증(`analysis/audit/verify_br_caxis.py` 재현 가능)**: BR을 라이브 발사로
  가정한 재생 결과 **발사분 실현 win% 28.6%**(exp_R +0.03·PF 1.07 — breakeven 노이즈) ≪
  floor 58% → **섀도 유지 확정**(win-rate-first 제약 위배). C축 v2로 재생해도 25.0%로
  구제 안 됨. → 사전등록 기준(win%≥55 ∧ exp_R>0 ∧ PF>1) 미통과.
- **회계 누수 수리(Tier 1, `wrf/logger.py`)**: 같은 봉의 이른 실행이 후보 0으로 행을
  선점하면(데이터 미정착) 후보를 생성한 재실행이 멱등 skip돼 **'발사했는데 JSONL만 빈 행'**
  이 남던 누수(라이브 26건 중 5건 — fire-rights·보정 원장이 현실보다 관대). `record_snapshot`이
  기존 행의 path가 아직 null(=같은 시각 재실행 창)이고 새 행이 후보가 더 많으면 교체하도록
  수리(결정적·전략무관, path 형성 행은 절대 훼손 안 함). 역사적 5건은 이미 path 형성돼
  소급 복구 불가(후보 데이터 소실) — 전방 재발만 차단.
- **본전스톱 검증→HOLD(Tier 1, `analysis/audit/verify_breakeven.py`)**: 저장 경로 봉순서
  리플레이로 {0.8,1.0,1.2} 플래토 검증. **전방 관련 모집단(non-BR 발사 n≈7)에서 효과 정확히
  0**(전부 TP직행/SL직행 — arming-후-반전 부재). 측정 이득은 전부 섀도 처리된 BR 모집단에
  국한 → C축 v2와 동일한 '제거된 모집단 신기루' → **미채택**. 데이터 축적 후 재실행으로
  자동 재판정(non-BR 플래토 개선 시 채택). 재무장 히스테리시스도 같은 이유로 보류(급성
  클러스터링 위험원 BR이 이미 섀도 — 재점등 시 동반 구현).
- **grind→TF 채널 재측정→현행 유지(Tier 2, `analysis/audit/verify_grind_tf.py`)**: 하락
  grind 숏의 올바른 주인은 페이드(밴드반전)가 아니라 TF(추세추종)이나, ADX 지연으로
  grind가 RANGING 오분류돼 TF가 배제된다. Pillar1 slope_sig가 유일한 구출 레버 → 전체
  820스냅샷(7월 DOWNLEG grind 포함)으로 실제 `classify_market_regime`을 직접 호출해 단일변수
  9종 스윕(분류 지표만 — 단일레짐 실현 R은 국면학습 함정). **전부 사전등록 게이트 탈락**:
  회수↑는 전부 chop-FP↑·정밀도↓로 상쇄(현행이 효율 프론티어). **grind-숏 회수 ~15%가 구조적
  상한**(느린 grind가 slope-persist에서 chop과 준-구별불가). er_pctl은 grind 회수에 무효
  (is_ranging 뒤 판정 — 설계상 chop-FP 보호). → **레짐 파라미터 무변경**. 함의: grind-숏
  빈도의 근본 회복은 튜닝이 아니라 신규 방향신호(Phase 4·다레짐 검증)의 몫 — 밴드반전
  승격이 메운 공백은 실재했으며 파라미터로 대체 불가임이 정량 확인됨.

</details>

<details>
<summary><b>밴드반전 원트랙 일원화 (구 D-shadow 투트랙 폐지)</b></summary>

구 **D-shadow**는 BB 밴드복귀 반전을 잡되 **섀도 전용**(라이브 발사 무영향, Notion '(shadow)'
별도 트랙)이었다. floor의 연속 min-axis·라우팅 역추세 억제가 충분한 품질 통제를 제공하므로
**원트랙으로 승격** — `_detect_band_reversal`(구 `_detect_d_shadow`)이 `setup=RV` 후보를 다른
디텍터와 **동일하게 라이브 발사**한다. 엔진이 `(setup,dir)` 중복은 더 높은 P̂만 남긴다. Notion은
'(shadow)' 표식 없이 일반 신호로 기록. 제거된 군더더기: `fired_shadow`·`shadow_fire`·
`shadow_logged`·`_shadow_cooldown_filter`·`recent_shadow_dirs`·`WRF_D_SHADOW_COOLDOWN_H`·
`analysis/shadow_report.py`. (near-miss `shadow_band`은 별개 — 유지.)
**→ [Phase A]에서 setup=BR로 분리 + 섀도 강등 — 위 항목 참조.**

</details>

<details>
<summary><b>감사 처방 구현 (2026-06, 4 pillar · win-rate-first 골격 유지 · 기본 ON)</b></summary>

위 grind-fix(ER 절대 0.50 승격 + BO near-SL)는 **fast trend·RR 산술**만 고쳐 정작 **slow
grind**는 놓쳤다(ER 0.50은 느린 grind의 ER 0.15~0.35를 영영 못 만남). 정량 감사 결과
"하드 AND 게이트 다단 직렬 + 추세정의 절대임계 + P̂/RR 분리"가 FN의 3중 구조원인으로 확정
(실측: precond 통과 50건 중 **38건(76%)이 floor=min-axis 하드절벽에서 사망**, BO는 RR에서 4/7
전사). 처방은 **하드 게이트를 점수로 강등하고 판정을 floor에 위임**하는 한 원리로 수렴한다.

- **Pillar1 — 레짐/라우팅 지연**: ① ER을 코인 자기분포 **백분위**로(`WRF_REGIME_ER_PCTL`,
  절대 0.50 폐기·철학 정합) ② **방향지속**(MA20 기울기 일관성 + **순드리프트 magnitude**) 승격을
  `is_ranging` 앞에 배치(`WRF_REGIME_SLOPE_PERSIST`) ③ 라우팅을 BTC매크로 종속에서 **심볼
  자체구조**로 분리(`WRF_ROUTING_SELF_STRUCT`). **★실데이터 튜닝(323스냅샷)**: 기울기 일관성만으론
  하락 grind(sp=0.74)와 chop(sp=0.79)이 분리 안 됨(slow grind는 backward 통계가 chop과 닮음) →
  드리프트 AND 게이트(≥0.02) + 임계 상향(0.85)으로 chop 오승격을 42%→**8%**로 통제. 회수율은
  보수적(하락추세 21%) — 초저속 grind는 FP 통제 비용으로 일부 미승격(숏 FN의 주 해결은 Pillar2).
- **Pillar2 — precond 경직성**: RV 5중 동시 AND를 **소프트 스코어**로(`WRF_RV_SOFT_PRECOND`) —
  안전 최소치(소진≥1∧반전캔들∧확인≥2)만 게이트, CHoCH·리테스트는 L 감쇠로 흡수(부분정렬
  반전도 후보화하되 약하면 floor가 탈락). BO near-SL은 **타이트니스 P̂ 보정**(`WRF_BO_SL_TIGHT_PEN`)
  으로 SL을 당긴 만큼 실제 승률↓를 prior에 반영.
- **Pillar3 — min-axis/RR 병목**: ① min-axis 하드절벽(0.55 고정=위장 하드베토)을 **연속 페널티**
  로(`WRF_PRIOR_MIN_AXIS_SOFT`) — 0.10 근방 매끄럽게(near-miss 회복)·음수축은 강차단, prior·보정
  일관 적용(불연속 제거) ② 고정 RR≥1.5를 **EV-결합 게이트**로(`WRF_EV_GATE`, EV=P̂·RR−(1−P̂)≥0.15)
  → 고확률·중RR 셋업 회생, win-rate-first(MR TP=mid)와 정합.
- **Pillar4 — 숨은 L/S 비대칭**: `pct_rank` **midrank**(동점 +1/(2n) 편향 제거·완전대칭),
  TF 모멘텀 **대칭화**(숏도 명시적 약세 요구), `WRF_RV_SIDED_SIGNALS` 기본 ON(청산을 진입방향
  적합한 쪽만), 死파라미터 `WRF_PCT_EXTREME_*` 배선.

**검증(`analysis/audit/` 재현 가능)**: ① **실데이터 레짐 재현**(323스냅샷, p0=실종가·
raw.adx=실ADX) — 하락추세 회수 21%(전부 숏 적격)·chop 오승격 8%·승격 정밀도 62%·TRENDING률
3.1%→18%(타당). ② 게이트 재채점(실데이터 50후보) — 연속 min-axis가 floor에서 죽던 후보 부활,
집계 성능은 실제 라이브 이력과 정합(PF 3.16). ③ 합성 컴포넌트 9/9 — grind 상/하 대칭 승격·chop
미승격 / 알트 grind는 BTC=CHOP에도 route=down / RV 부분정렬 숏 0→1 생성 / min-axis 단조연속
(음수축 강차단) / EV게이트 0.65×1.0 회생 / midrank 완전대칭 / BO RR 0.99→3.33.
④ **핵심 진단**: 숏 발사 수는 게이트 재채점만으로 불변 + 레짐신호가 하락 grind를 chop과 분리
못함 → 숏 FN의 주 해결은 **Pillar2(RANGING 내 RV 생성)**, Pillar1은 FP-안전 보조. (표본 ≈5일·
단일레짐 → 모든 수치는 인프라/논리 검증용, OOS 재검증 전제.)

</details>

<details>
<summary><b>느린 추세 숏 부재 진단 + grind-fix (2026-06, 과적합 경계)</b></summary>

**관찰**: BTC/ETH/HYPE가 KST 23시경 반전 후 −4.6~8.7% 하락하는 내내 숏 신호가 한 건도
나오지 않음(전체 데이터셋 누적: **롱 7발사 / 숏 0발사**). JSONL 실측 진단:

- **레짐 오분류(루트원인)**: ADX는 지연 지표라 느린 grind-down이 내내 ADX<25에 머묾 →
  1H `RANGING`+4H `SQUEEZE` 고착. 라우팅상 **추세추종 TF가 원천 배제**(TF는 4H가
  TRENDING/EXPLOSIVE일 때만 보강). RSI 67→24·MACD +153→−217·BB%b 1.0→0.0 의 명백한
  단조하락을 ADX가 못 잡음. 분류기는 효율비(ER)를 계산하나 RANGING 판정에만 쓰고 있었음.
- **셋업별 사인**: MR=반전(역추세) 도구라 고점엔 반전캔들 부재·하락 중엔 오히려 롱 지향 |
  RV=CHoCH 필수인데 점진적 롤오버라 choch 미발생 | BO=막판에야 후보 형성, 그나마
  **SL이 박스 반대편(far)이라 손절=박스높이 → RR≈1**(BTC 0.99/ETH 0.91)로 발사컷.
- **veto·플로어는 무죄**: 숏은 DOWNLEG 정합이라 거시베토 없음, BO p̂=0.65>플로어. 순수 RR.

</details>

<details>
<summary><b>레이어 연결 완성도 보강 (2026-06, 과적합 경계)</b></summary>

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

</details>

<details>
<summary><b>전략 정합 개선 (2026-06, win-rate-first 골격 유지)</b></summary>

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
  스파이크 유지 + 펀딩 컨트래리언 L 가점.) *[2026-07-07 수리]* 분자를 '완성'봉(`iloc[-2]`)
  으로 정렬 — 미완성 형성봉 참조로 게이트가 상시-거짓이던 반전 계통 FN 버그 해소.

</details>

---

<a id="roadmap"></a>
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
| 보정(L3) | Phase 2 부분풀링 구현(✅), 그림자 운영 | 심장 재시동 — 발사반영은 OOS 입증 후 |
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

### Phase 2 — 학습 부활: 계층적 부분풀링 보정 (✅ 구현 완료) · *"심장을 다시 뛰게"*

구(舊) 자격게이트(셀당 독립 N≥100 × 거시≥2종)는 수개월~수년이 걸려 **영구히 도달 불가**
였다(실효≈0, 심장 정지). 이를 **부분풀링(partial pooling)** 으로 교체해 보정엔진을 되살렸다.
**기능은 완비됐고, 발사 반영은 OOS 우위 입증 후**(아래 Gate-Out)로 미뤄 과적합을 차단한다.

- ✅ **계층적 random-intercept 로지스틱 (`analysis/calibrate.py`)**: 계층 GLOBAL→SETUP→
  BASE(setup×regime)→CELL(setup×regime×macro). **prior 기울기(wC/wL/wF)는 고정**(소표본에서
  (C,L,F) 재학습 금지)하고, 셀별 **절편 오프셋 δ_eff만** 학습. 자격 0/1 이분법 폐기.
- ✅ **Beta-Binomial 수축**: `wr_pooled = (wr_obs·n_indep + wr_parent·k)/(n_indep+k)`. 표본
  적으면 부모로 회귀, 쌓이면 자기 셀로 수렴. 수축의 n은 **독립표본 n**(72h 탈상관, stride 24h).
- ✅ **δ_eff = clamp(conf·δ, ±delta_cap)**, `conf = n_indep/(n_indep+k_conf)`,
  `δ = logit(wr_pooled) − logit(prior_raw_mean)`. 라이브: `P̂ = min(calib_cap, σ(prior_logodds+δ_eff))`.
- ✅ **과적합 가드 5중**: ①기울기 고정 ②부모 수축 ③신뢰도 가중 δ ④δ 하드캡 ⑤그림자 운영.
- ✅ **베타착시 가드**: 부모가 거시방향별로 승률 갈리면(한쪽만 성립) conf 페널티(×0.5).
- ✅ **A/B 그림자 평가 (`backtest.py --ab`)**: 엔진이 매시간 prior·보정 P̂을 **동시 기록**
  (`p_prior`/`p_cal`), Brier·캘리브레이션으로 OOS 우위를 측정. 우위 입증 전까진 발사는 prior.
- ✅ **주간 보정 잡 (`.github/workflows/calibrate.yml`)**: 일요일 04:10 UTC, JSONL→δ_eff 학습→
  `calibration_table.json` 커밋. 라이브는 이 산출물의 δ_eff만 읽는다(학습은 여기서만).

> **점검 산출(현 데이터)**: 결판 10건 기준, 단일표본 셀(wr=1.0/0.0)은 `min_decided=3` 미달로
> 보정 비활성 + pooled가 ~0.4로 강하게 수축(과적합 차단 확인). 보정활성 셀의 δ_eff는 ~0.016로
> prior에 밀착(conf≈0.09). A/B Brier Δ≈0 — 데이터 부족이라 보정이 prior를 그림자처럼 따라간다.
>
> **Gate-In**: Phase 1 실현승률 테이블 존재(✅). **Gate-Out**: 유니버스 6+가 다거시레짐을
> 커버하고 결판 표본이 충분해진 뒤, `backtest.py --ab`의 **OOS(시간분할+72h embargo) Brier·
> 기대R 우위**가 확인되면 → Variable로 `WRF_CALIB_DISABLED=false` 전환(보정 P̂으로 발사).

### Phase 3 — 발사·청산·사이징 고도화 (중기) · *"이기는 거래를 키운다"*

승률이 검증되면, **기대값을 극대화**하는 체결·자금관리 레이어로 확장.

- **부분익절 / 트레일링 / 본전스톱**: 현 단일 TP/SL/타임아웃 → 1차 부분익절 후
  ATR 트레일링 + 본전이동(런너 확보). 스윙 추세의 비대칭 페이오프 포착.
  (TF 트레일링은 P2로 선행 착수 — [실험 로그](#changelog) 참조. 나머지 셋업·부분익절·
  본전스톱은 여전히 이 단계 몫.)
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

---

<a id="disclaimer"></a>
## 면책 조항

본 소프트웨어는 교육·연구 목적의 시그널 도구이며 투자 자문이 아닙니다. 암호화폐
선물 거래는 높은 손실 위험을 동반합니다. 모든 매매 판단과 결과의 책임은 사용자에게 있습니다.
