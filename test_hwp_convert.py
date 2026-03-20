# -*- coding: utf-8 -*-
"""HWP -> HWPX 변환 테스트 (pyhwpx COM 자동화)"""
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pyhwpx as hwp

TEST_HWP = Path(r"C:\Users\user\Downloads\업무파악\make\messenger_rag\attachments\69129ac9ce6881122e000001\2025. 2학기 학습코칭 명단(삼양초).hwp")
OUT_HWPX = TEST_HWP.with_suffix(".hwpx")

print(f"입력: {TEST_HWP.name}")
print(f"출력: {OUT_HWPX.name}")

h = hwp.Hwp()
try:
    h.open(str(TEST_HWP))
    result = h.save_as(str(OUT_HWPX), format="HWPML2X")
    print(f"save_as 결과: {result}")
    if OUT_HWPX.exists():
        print(f"완료! 크기: {OUT_HWPX.stat().st_size:,} bytes")
    else:
        print("파일이 생성되지 않았습니다.")
except Exception as e:
    print(f"오류: {e}")
finally:
    h.quit()
