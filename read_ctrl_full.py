# -*- coding: utf-8 -*-
"""noteDetail_controller.js 전체 소스 + _mainWindow 접근"""
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

# 1. _mainWindow 접근 시도
print("=== _mainWindow 접근 ===")
r = js(ws, 2, """
var result = {};
try {
    var _m = window.opener;
    result.has_opener = !!_m;
    if(_m) {
        result.opener_href = _m.location.href;
        result.has_common = typeof _m.common_controller !== 'undefined';
        result.has_note_ctrl = typeof _m.note_controller !== 'undefined';
        result.main_funcs = Object.keys(_m).filter(function(k){ return /note|controller/i.test(k); }).slice(0,10);
    }
} catch(e) {
    result.error = e.message;
}
// noteDetail_controller도 확인
result.has_noteDetail_ctrl = typeof noteDetail_controller !== 'undefined';
result.has_noteDetail_view = typeof noteDetail_view !== 'undefined';
JSON.stringify(result)
""")
print(r)

# 2. noteDetail_controller의 내부 API 직접 호출
print("\n=== noteDetail_controller.noteDetail() 직접 호출 ===")
import sqlite3
from pathlib import Path
DB_PATH = Path(__file__).parent / "messages.db"
conn = sqlite3.connect(DB_PATH)
samples = [r[0] for r in conn.execute("SELECT note_code FROM notes WHERE file_cnt > 0 LIMIT 3").fetchall()]
conn.close()

r2 = js(ws, 3, f"""
var result = 'not tried';
try {{
    if(typeof noteDetail_controller !== 'undefined') {{
        // noteDetail 함수 호출 시도
        var nd = noteDetail_controller.noteDetail;
        if(typeof nd === 'function') {{
            nd('{samples[0]}');
            result = 'noteDetail() called';
        }} else {{
            result = 'noteDetail is not function: ' + typeof nd;
        }}
    }} else {{
        result = 'noteDetail_controller not found';
    }}
}} catch(e) {{
    result = 'error: ' + e.message;
}}
result
""")
print(r2)

# 3. controller.js 핵심 부분 - noteDetail API 호출 코드 찾기
print("\n=== noteDetail_controller.js 핵심 API 호출 부분 ===")
def fetch(url):
    req = urllib.request.Request(url)
    req.add_header("Cookie", cookie)
    req.add_header("User-Agent", "Mozilla/5.0")
    return urllib.request.urlopen(req, timeout=10).read().decode("utf-8", errors="replace")

ctrl = fetch(f"{BASE}/resources/pc/js_module/note/noteDetail_controller.js")

# _noteDetail 함수 내용 전체 (note detail API 호출 부분)
note_detail_func = re.search(r'var _noteDetail\s*=\s*function\s*\([^)]*\)\s*\{(.+?)(?=\n    var \w+\s*=\s*function|\nreturn\s*\{)', ctrl, re.DOTALL)
if note_detail_func:
    content = note_detail_func.group(1)
    # API 호출 부분만
    api_calls = re.findall(r'(?:ajax|callApi|request|fetch)[^;]{0,300}', content)
    for call in api_calls[:5]:
        print(call[:400])
        print("---")

    # 전체 함수 앞부분 (파라미터 확인)
    print("\n--- _noteDetail 함수 시작 부분 ---")
    print(content[:1000])

# 4. common_controller의 API 호출 패턴
print("\n=== common_controller.js의 API 호출 래퍼 ===")
common = fetch(f"{BASE}/resources/pc/js_module/common/common_controller.js")

# callApi 또는 ajax 래퍼 함수 찾기
for match in re.finditer(r'(?:callApi|serverRequest|ajaxCall)\s*[:=]\s*function\s*\([^)]{0,100}\)\s*\{[^}]{0,500}', common):
    print(match.group()[:500])
    print("---")
    break

ws.close()
