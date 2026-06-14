# analysis/ — 오프라인 학습 데이터 분석 유틸

`data/research/{SYMBOL}/{YYYY-MM}.jsonl`(매시간 상태 스냅샷 + 72h 경로)을
읽어 **라벨을 사후 파생**하고 상황별 분포를 본다. 봇 본체(`src/`)와 완전 분리 —
라이브 신호에 영향 없음. 설계: [`../docs/LEARNING_DATA_DESIGN.md`](../docs/LEARNING_DATA_DESIGN.md).

## 파일
| 파일 | 역할 |
|------|------|
| `build_dataset.py` | JSONL → 평탄 DataFrame + 경로 파생 라벨(수익률·MFE/MAE·경로효율·TP/SL 재생) |
| `situation_report.py` | 지문/레짐별 경로 분포 집계 리포트 (+통계 주의 머리말) |

## 사용
```bash
# 데이터 적재 현황 요약
python analysis/build_dataset.py

# 데이터셋 저장(파생 라벨 포함)
python analysis/build_dataset.py --out /tmp/ds.parquet

# 상황별 분포 (레짐1H×레짐4H×일봉바이어스)
python analysis/situation_report.py

# 전체 지문 키 기준 + TP/SL 재생(롱, 3.6%/2.0% = 1.8R)
python analysis/situation_report.py --by key --sim long --tp 0.036 --sl 0.020
```

## 라벨 정의 (경로에서 파생)
- `ret_{4,12,24,48,72}h` — **다음 봉 시가(o[0]) 진입** 기준 종가 수익률(현실적 체결, P2)
- `mfe_72h / mae_72h` — 최대유리/최대불리 변동, `mfe_6h / mae_6h` — 진입 직후 6h(빠른 손절 진단)
- `tt_peak / tt_trough` — 고점/저점 도달 시간(캔들 수)
- `path_eff` — 경로효율(1=일방향, 0=왕복)
- `simulate_tp_sl()` — 임의 TP/SL/방향을 경로 위에서 재생 → 승패·R배수

## 통계 규약 (반드시 준수)
매시간 표본은 72h 윈도가 겹치는 **자기상관 표본**이다.
- train/test: **시간순 분할 + 72h embargo**(purged CV). 무작위 분할 금지.
- 셀 최소 표본(`--min-n`, 기본 30) 미만은 참고용. 결론·실거래 반영 금지.
- 수백 셀 다중비교 → 우연한 '성배' 발생. **out-of-sample 재검증 필수**.
- 심볼 풀링은 ATR 단위 표현 덕에 가능하나 `symbol` 항상 보유 → 풀링/개별 비교.
