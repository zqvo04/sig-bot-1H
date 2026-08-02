# 감사 처방 검증 스크립트 (repo 루트에서 실행)

저장소 루트에서 `python3 analysis/audit/<script>.py` 로 실행한다(상대경로 `src/`·`data/research/` 사용).

- `verify_realdata_regime.py` — **실데이터 레짐 FN/FP**. JSONL의 p0(실종가)·raw.adx(실ADX)로
  OLD↔NEW 레짐을 재현, path(실제 forward)로 라벨링해 추세회수/ chop오승격 혼동행렬.
- `tune_regime.py` — Pillar1 승격신호(slope/ER/drift/R²)의 DIR-vs-CHOP 판별력 진단 + 임계 sweep.
- `verify_rescoring.py` — **Pillar3 게이트 재채점**(실데이터 동결후보). OLD(하드 min-axis+RR≥1.5)
  vs NEW(연속 min-axis+EV게이트) 발사집합·실현승률 비교.
- `verify_fp_discrimination.py` — floor+EV 게이트의 승자/패자 분별력(FP 통제 근거).
- `verify_components.py` — Pillar1/2/4 + 원트랙 합성 컴포넌트 테스트(논리 검증, 9 체크).
- `diagnose_fp_fn.py` — **FP/FN 잔존 진단**(docs/DIAGNOSTIC_2026-08_FPFN.md 재현). 저장 후보를
  현행 config로 재채점해 게이트 퍼널·코호트 엣지(승률−1/(1+RR))·P̂ 변별력 분해(전체/셋업내부/
  base-rate AUC)·재적합 계수 비식별성을 보고. `--geometry` TP/SL 격자 스윕, `--walkforward`
  (setup,dir) base-rate 대조군.

⚠ 표본 ≈5일·단일 거시레짐 → 모든 수치는 인프라/논리 검증용, OOS(시간분할+72h embargo) 재검증 전제.
