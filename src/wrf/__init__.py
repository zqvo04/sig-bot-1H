"""WRF-4 (Win-Rate-First, 4-Setup) 엔진 패키지.

L0 VETO → L1 직교 3축(C/L/F, 백분위) → L2 4셋업 디텍터 → L3 보정 승률 P̂
→ L4 발사+청산. 라이브는 무상태·페이퍼 전용이며 절대 학습하지 않는다
(calibration_table.json만 읽음). 본체는 main에서 try/except로 격리된다.
"""
