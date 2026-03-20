# -*- coding: utf-8 -*-
"""
HWP → HWPX 일괄 변환
attachments/ 하위의 모든 .hwp 파일을 .hwpx로 변환
"""
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pyhwpx as hwp

ATTACH_DIR = Path(__file__).parent / "attachments"

hwp_files = sorted(ATTACH_DIR.rglob("*.hwp"))
print(f"HWP 파일 총 {len(hwp_files)}개 발견\n")

h = hwp.Hwp()
success = 0
skip = 0
fail = 0

try:
    for i, hwp_path in enumerate(hwp_files, 1):
        hwpx_path = hwp_path.with_suffix(".hwpx")

        if hwpx_path.exists():
            print(f"[{i}/{len(hwp_files)}] [skip] {hwp_path.name}")
            skip += 1
            continue

        try:
            h.open(str(hwp_path))
            ok = h.save_as(str(hwpx_path), format="HWPML2X")
            if ok and hwpx_path.exists():
                print(f"[{i}/{len(hwp_files)}] ✓ {hwp_path.name} ({hwpx_path.stat().st_size:,} B)")
                success += 1
            else:
                print(f"[{i}/{len(hwp_files)}] ✗ {hwp_path.name} (저장 실패)")
                fail += 1
        except Exception as e:
            print(f"[{i}/{len(hwp_files)}] ✗ {hwp_path.name} | {e}")
            fail += 1
finally:
    h.quit()

print(f"\n완료: 성공 {success} | 건너뜀 {skip} | 실패 {fail}")
