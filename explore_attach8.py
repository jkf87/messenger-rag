# -*- coding: utf-8 -*-
"""noteDetail 전역 변수 전체 내용 + postMessage 전환 시도"""
import sys, json, urllib.request, time, sqlite3
from pathlib import Path
from websocket import create_connection

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CDP_URL = "http://127.0.0.1:9000/json"
DB_PATH  = Path(__file__).parent / "messages.db"

def js(ws, id_, expr):
    ws.send(json.dumps({"id": id_, "method": "Runtime.evaluate",
                        "params": {"expression": expr}}))
    return json.loads(ws.recv()).get("result", {}).get("result", {}).get("value", "")

pages = json.loads(urllib.request.urlopen(CDP_URL, timeout=3).read())
for p in pages:
    print(p.get('type'), p.get('url','')[:80], 'ws' if 'webSocketDebuggerUrl' in p else 'NO_WS')

note_page = next((p for p in pages if "noteDetail" in p.get("url","") and "webSocketDebuggerUrl" in p), None)
ws = create_connection(note_page["webSocketDebuggerUrl"], timeout=15)

# 1. window.noteDetail 전체 (파일 정보 있는지 확인)
print("\n=== window.noteDetail 전체 item 필드 ===")
r = js(ws, 1, """
try {
    var key = Object.keys(window.noteDetail)[0];
    var item = window.noteDetail[key].item;
    JSON.stringify(item)
} catch(e) { 'error: ' + e.message }
""")
if r and r != 'undefined':
    try:
        item = json.loads(r)
        print(json.dumps(item, ensure_ascii=False, indent=2))
    except:
        print(r[:1000])

# 2. noteDetail 내 inline script 내용 확인
print("\n=== inline script 분석 (note load 로직) ===")
r2 = js(ws, 2, """
var scripts = Array.from(document.querySelectorAll('script:not([src])'));
var relevant = scripts.filter(function(s){
    return s.textContent.includes('noteCode') || s.textContent.includes('NTE_CODE') || s.textContent.includes('fileurl');
}).map(function(s){ return s.textContent.substring(0,500); });
JSON.stringify(relevant.slice(0,3))
""")
try:
    scripts = json.loads(r2)
    for i, s in enumerate(scripts):
        print(f"--- Script {i} ---")
        print(s)
except:
    print(r2[:500])

# 3. main 페이지 WS 재시도
print("\n=== main 페이지 WS 재확인 ===")
pages2 = json.loads(urllib.request.urlopen(CDP_URL, timeout=3).read())
main_p = next((p for p in pages2 if "main" in p.get("url","") and "webSocketDebuggerUrl" in p), None)
if main_p:
    print(f"main WS 사용 가능: {main_p['webSocketDebuggerUrl'][:60]}")
    ws_main = create_connection(main_p["webSocketDebuggerUrl"], timeout=10)

    # main 페이지에서 다른 쪽지 클릭
    conn = sqlite3.connect(DB_PATH)
    targets = conn.execute("SELECT note_code, title FROM notes WHERE file_cnt > 0 LIMIT 5").fetchall()
    conn.close()

    print("쪽지 목록 (file_cnt > 0):")
    for code, title in targets:
        print(f"  {code} | {title[:40]}")

    # main 페이지에서 noteDetailOpen 또는 noteView 유사 함수 찾기
    r3 = js(ws_main, 10, """
    JSON.stringify(Object.keys(window).filter(function(k){
        return typeof window[k]==='function' && /note.*detail|detail.*note|open.*note|note.*open|note.*view|view.*note/i.test(k);
    }))
    """)
    print(f"\nmain 쪽지 관련 함수: {r3}")

    # postMessage로 noteDetail에 쪽지 코드 전달 시도
    target_code = targets[1][0]  # 두 번째 쪽지
    print(f"\n=== postMessage로 noteDetail 전환 시도: {target_code} ===")
    r4 = js(ws_main, 11, f"""
    // noteDetail 창 찾기
    var noteWin = null;
    for(var i=0; i<window.frames.length; i++) {{
        try {{
            if(window.frames[i].location.href.includes('noteDetail')) {{ noteWin = window.frames[i]; break; }}
        }} catch(e) {{}}
    }}
    var result = noteWin ? 'frame found' : 'no frame';
    // 직접 함수 호출 시도
    try {{
        if(typeof noteDetailOpen === 'function') {{ noteDetailOpen('{target_code}'); result += ' | noteDetailOpen called'; }}
        if(typeof noteOpen === 'function') {{ noteOpen('{target_code}'); result += ' | noteOpen called'; }}
    }} catch(e) {{ result += ' | error: ' + e.message; }}
    result
    """)
    print(f"결과: {r4}")
    ws_main.close()
else:
    print("main WS 여전히 없음")

    # 대안: noteDetail 페이지에서 opener를 통해 접근
    print("\n=== window.opener 통해 main 접근 ===")
    r5 = js(ws, 20, f"""
    var result = '';
    try {{
        if(window.opener) {{
            result = 'opener exists: ' + window.opener.location.href;
            if(typeof window.opener.noteDetailOpen === 'function') {{
                window.opener.noteDetailOpen('{targets[1][0] if targets else ""}');
                result += ' | noteDetailOpen called via opener';
            }}
        }} else {{ result = 'no opener'; }}
    }} catch(e) {{ result = 'error: ' + e.message; }}
    result
    """)
    print(r5)

ws.close()
