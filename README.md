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
   BO: 경계돌파 + 거래량스파이크 + [리테스트 유지★필수] + 펀딩컨트래리언 가점
       (RANGING/SQUEEZE/EXPLOSIVE 도달) | TP=박스높이 SL=돌파경계 near∓ATR(RR정상화) T=36h
   MR(RANGING): BB극단 + RSI극단백분위 + 반전마이크로 + 반전봉거래량 |
       TP=박스중심선/반대편경계 SL=박스경계∓ATR T=24h
   RV: 다이버전스 + 반전캔들 + [확인≥2] + 반전봉거래량 (CHoCH·리테스트는 소프트=L감쇠) |
       TP=직전레벨 SL=극단너머 T=48h
   밴드반전(RV·원트랙): BB 밴드복귀(상단→복귀=숏/하단→복귀=롱) 라이브 발사 (구 D-shadow 일원화)
L3 보정 승률 P̂: isotonic(로지스틱(C,L,F)) · 셀=(setup×regime_1h×btc_macro)
   └ 신뢰게이트 미충족 → 보수적 고정 prior (콜드스타트)
   └ ★셀 키는 거친 채로 둔다(콜드스타트·과적합 보호). 누락 맥락(4H추세·일봉EMA20/50)은
     셀 키를 늘리는 대신 C축에 연속 피처로 주입 → 셀 내부에서 분리 학습.
L4 발사+청산: 발사 ⟺ P̂ ≥ W_floor ∧ ¬VETO ∧ ¬격리[Phase A: 섀도셋업(BR)·발사권강등 셀]
   → TP/SL/타임스톱 산출, 사이징 ∝ P̂ (페이퍼)
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
| **TF** 추세추종 | 4H EMA정렬 + [얕은눌림(1H EMA밴드) ∪ 깊은눌림(4H피보 50~61.8%)] + (모멘텀 재정렬 ∨ BOS) + 반전봉 거래량 | C=`_ctx_align`(정합) · L=눌림품질(깊을수록↑, 성숙late 감쇠)+컨플루언스 · F=`_flow_align`(모멘텀 동조) | TP=측정이동(R배수 2.5) · SL=직전스윙∓ATR×1.5 · T=48h |
| **BO** 돌파 | 박스경계 돌파(종가) + 거래량스파이크(≥1.5×) + 리테스트 후 유지(2봉)★ + 펀딩 컨트래리언 가점 | C=정합 · L=박스폭+펀딩+컨플루언스 · F=정합 | TP=박스높이 · SL=**돌파경계 near∓ATR**(RR≈박스/ATR) · 타이트시 P̂보정 · T=36h |
| **MR** 평균회귀 | BB %b 극단(≤0.1/≥0.9) + RSI 백분위 극단(`WRF_PCT_EXTREME`=0.15/0.85, 이제 배선) + 반전캔들 + 반전봉 거래량 | C=`_ctx_exhaustion`(소진) · L=극단깊이+컨플루언스 · F=`_flow_exhaustion`(컨트래리언) | TP=박스중심선/반대편 · SL=박스경계∓ATR · T=24h |
| **RV** 전환 | 소진≥1 + 반전캔들★ + 총확인≥2 **(CHoCH·리테스트는 소프트 — 하드 아님, 부재 시 L 감쇠)** + 반전봉 거래량 | C=소진 · L=확인수−(CHoCH/리테스트 부재 감쇠)+컨플루언스 · F=컨트래리언 | TP=직전레벨(R배수 2.0) · SL=극단너머 · T=48h |

### C. 직교 3축 산출식 (`detectors.py`, ∈[-1,1])

```
추종형(TF/BO)
  C=_ctx_align    : 0.45·거시 + 0.25·바이어스 + 0.20·4H추세 + 0.10·일봉EMA20/50  (롱+/숏−)
  F=_flow_align   : 0.45·MACD백분위 + 0.25·테이커 + 0.20·스마트머니 + 0.10·OI사분면
반전형(MR/RV/BR)
  C=_ctx_exhaustion: 0.25 + 0.75·(페이드 대상 거시레그 신선도)   ← CHOP 완만통과, 신선역행 차단
    · [Phase C] v2(WRF_REV_CTX_V2, 기본 OFF): 0.25 + 0.75·(심볼-로컬 구조정합 _ctx_struct_align)
      = macro echo 포화(고유값 3개) 해소 · envelope[-0.5,1.0]·극단 불변, 중간 해상도만 추가
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
```

---

## 심볼 / 시크릿 / 파라미터

- **심볼**: `BTC/USDT ETH/USDT HYPE/USDT` (확장: SOL/SUI/XRP)
- **Secrets**: `OKX_API_KEY/SECRET/PASSPHRASE`, `TELEGRAM_BOT_TOKEN/CHAT_ID`,
  `NOTION_TOKEN`, `NOTION_SIGNALS_DB_ID` / `NOTION_SNAPSHOTS_DB_ID`(또는
  `NOTION_PARENT_PAGE_ID`로 자동 생성)
- **Variable**: `ALERT_ENABLED`, `WRF_*` 파라미터 오버라이드
- **실질 튜닝(3~5개)**: `WRF_PCT_WINDOW`(백분위 윈도), `WRF_PCT_EXTREME_HI/LO`(극단컷 —
  이제 MR RSI 극단을 실제 구동, 구버전은 死파라미터였음), `WRF_WIN_FLOOR`(승률 플로어),
  `WRF_CELL_N_MIN`(신뢰게이트). 단일변수·워크포워드.
- **전략 정합 토글**(전부 되돌리기 가능): `WRF_SL_ATR_CUSHION`(구조SL ATR쿠션, 0=구동작),
  `WRF_MR_TP_TARGET`(mid|opposite), `WRF_MR_BOX_WINDOW`, `WRF_RV_REQUIRE_CHOCH/RETEST`(전환
  시퀀스 강제), `WRF_TF_FIB_PULLBACK`(피보 깊은눌림 경로), `WRF_REV_VOL_MULT`(반전봉 거래량
  게이트, 0=OFF), `WRF_BO_FUND_BONUS`(돌파 펀딩 컨트래리언 가점).
- **레이어 연결 토글**: `WRF_BO_IN_RANGING`(RANGING 박스돌파 허용), `WRF_RV_MACRO_EXEMPT`
  (RV 거시베토 면제), `WRF_TF_LATE_MATURITY_MULT`(성숙추세 TF 감쇠, 1.0=없음),
  `WRF_CONFLUENCE_L_BONUS`(컨플루언스→L 가점, 0=OFF).
- **[Phase C] 반전형 C축 토글**: `WRF_REV_CTX_V2`(심볼-로컬 구조정합 주입, 기본 **OFF** —
  macro-echo 포화 해소, UPLEG 관측 후 점등 게이트. true=v2 점등, 즉시 되돌리기).
- **[Phase A] 발사권 게이트 토글**: `WRF_SHADOW_SETUPS`(섀도 셋업 목록, 기본 `BR` —
  빈 문자열=전부 라이브), `WRF_FIRE_RIGHTS_ENABLED`(강등 셀 격리, 기본 true),
  `WRF_FR_PRIOR_N`(사후검정 중립 prior 의사관측수 10), `WRF_FR_DEMOTE_P`(강등선 0.15),
  `WRF_FR_PROMOTE_P`(복권선 0.50), `WRF_FR_MIN_DECIDED`(강등 최소 발사결판 8) —
  거버넌스 상수(튜닝 파라미터 아님·워크포워드 대상 제외).
- **감사 처방 토글**(기본 **ON** — 감사 4 pillar 구현, 전부 되돌리기 가능): `WRF_REGIME_ER_PCTL`
  (ER 백분위화)·`WRF_REGIME_SLOPE_PERSIST`(방향지속 승격)·`WRF_ROUTING_SELF_STRUCT`(라우팅 BTC
  종속성 분리)·`WRF_REGIME_ADX_SOLE`(ADX 단독 TRENDING 트리거 — 기본 **강등**(false)·true=구동작.
  후행 ADX 스파이크는 소진/반전 직전이라 추종 라우팅이 음(−)스킬[추종 15% vs 기준 37%]이므로
  검증 후 강등; 확인된 추세(slope_sig·er_sig)는 불변) — Pillar1 |
  `WRF_RV_SOFT_PRECOND`(RV 하드AND→소프트) — Pillar2 |
  `WRF_PRIOR_MIN_AXIS_SOFT`(min-axis 연속화)·`WRF_EV_GATE`(EV-결합 RR게이트)·`WRF_EV_RR_FLOOR`
  (RR 하한, 기본 **0.85**=완화·1.0=구동작 — RR<1.0 잔존플로어가 EV-게이트 취지와 모순해 고확신
  BO숏을 동결하던 것을 검증 후 완화) — Pillar3 |
  `WRF_PCT_MIDRANK`·`WRF_TF_MACD_SYM`·`WRF_RV_SIDED_SIGNALS` — Pillar4. 기존 grind-fix
  `WRF_REGIME_ER_TREND`·`WRF_BO_SL_NEAR`·`WRF_REGIME_ROUTING`도 기본 ON으로 승격.

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

### 느린 추세 숏 부재 진단 + grind-fix (2026-06, 토글 OFF·과적합 경계)

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

### 감사 처방 구현 (2026-06, 4 pillar · win-rate-first 골격 유지 · 기본 ON)

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

### 밴드반전 원트랙 일원화 (구 D-shadow 투트랙 폐지)

구 **D-shadow**는 BB 밴드복귀 반전을 잡되 **섀도 전용**(라이브 발사 무영향, Notion '(shadow)'
별도 트랙)이었다. floor의 연속 min-axis·라우팅 역추세 억제가 충분한 품질 통제를 제공하므로
**원트랙으로 승격** — `_detect_band_reversal`(구 `_detect_d_shadow`)이 `setup=RV` 후보를 다른
디텍터와 **동일하게 라이브 발사**한다. 엔진이 `(setup,dir)` 중복은 더 높은 P̂만 남긴다. Notion은
'(shadow)' 표식 없이 일반 신호로 기록. 제거된 군더더기: `fired_shadow`·`shadow_fire`·
`shadow_logged`·`_shadow_cooldown_filter`·`recent_shadow_dirs`·`WRF_D_SHADOW_COOLDOWN_H`·
`analysis/shadow_report.py`. (near-miss `shadow_band`은 별개 — 유지.)
**→ [Phase A]에서 setup=BR로 분리 + 섀도 강등 — 아래 참조.**

### [Phase A] BR 셋업 분리 + 발사권(fire-rights) 게이트 (2026-07)

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

### [Phase C] 반전형 C축 v2 — macro-echo 포화 해소 (기본 OFF · 과적합 경계)

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
│   ├── labels.py                # triple-barrier·exret·class·candidate_dataset
│   ├── calibrate.py             # ★[Phase 2] 부분풀링 보정 잡(계층 수축→셀별 δ_eff)
│   ├── backtest.py              # ★[Phase 1] 백테스트/리플레이 하니스(성능+퍼널)
│   ├── situation_report.py      # 상황·WRF 셀 진단(+ --perf 하니스 위임)
│   └── routing_scorecard.py     # 레짐 라우팅-유틸리티 스코어카드(추종vs반전 실현R·오프라인 측정)
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
