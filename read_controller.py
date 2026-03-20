# -*- coding: utf-8 -*-
"""noteDetail_controller.js 분석 - 초기화 및 파일 로드 함수"""
import sys, json, urllib.request, re
from websocket import create_connection

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CDP_URL = "http://127.0.0.1:9000/json"
BASE    = "http://stmsg.cbe.go.kr:7880"

pages = json.loads(urllib.request.urlopen(CDP_URL, timeout=3).read())
note_page = next(p for p in pages if "noteDetail" in p.get("url","") and "webSocketDebuggerUrl" in p)
ws = create_connection(note_page["webSocketDebuggerUrl"], timeout=15)

def js(ws, id_, expr):
    ws.send(json.dumps({"id": id_, "method": "Runtime.evaluate", "params": {"expression": expr}}))
    return json.loads(ws.recv()).get("result", {}).get("result", {}).get("value", "")

cookie = js(ws, 1, "document.cookie")
ws.close()

def fetch(url):
    req = urllib.request.Request(url)
    req.add_header("Cookie", cookie)
    req.add_header("User-Agent", "Mozilla/5.0")
    return urllib.request.urlopen(req, timeout=10).read().decode("utf-8", errors="replace")

# noteDetail_controller.js 가져오기
print("=== noteDetail_controller.js ===")
ctrl = fetch(f"{BASE}/resources/pc/js_module/note/noteDetail_controller.js")
print(f"크기: {len(ctrl):,} chars\n")

# 전체 내용 출력 (중요 섹션만)
# 파일 관련 코드
print("--- FILE 관련 코드 ---")
for match in re.finditer(r'.{0,200}(?:fileurl|oriname|upload/note|FILE_CODE|fileCode|fileList|fileDown|downloadFile).{0,200}', ctrl):
    print(match.group()[:300])
    print()

print("--- init/ready 함수 ---")
# document.ready 또는 init 함수
for match in re.finditer(r'(?:document\.ready|\.ready\(|init\s*[:=]\s*function|\$\(function).{0,500}', ctrl, re.DOTALL):
    print(match.group()[:400])
    print()

print("--- noteDetail API 호출 ---")
for match in re.finditer(r'.{0,100}(?:noteDetail|note/view|note/file).{0,200}', ctrl):
    print(match.group()[:350])
    print()

# noteDetail_view.js도 확인
print("\n=== noteDetail_view.js - FILE 관련 ===")
view = fetch(f"{BASE}/resources/pc/js_module/note/noteDetail_view.js")
print(f"크기: {len(view):,} chars\n")

for match in re.finditer(r'.{0,150}(?:fileurl|oriname|fileDown|fileOpen|noteFile).{0,150}', view):
    print(match.group()[:350])
    print()

# common_controller.js에서 암호화 API 호출 패턴
print("\n=== common_controller.js - 암호화 API 패턴 ===")
common = fetch(f"{BASE}/resources/pc/js_module/common/common_controller.js")
print(f"크기: {len(common):,} chars")
for match in re.finditer(r'.{0,100}(?:enctype|aes256|body\[data\]).{0,200}', common):
    print(match.group()[:300])
    print()
    break  # 첫 번째만
