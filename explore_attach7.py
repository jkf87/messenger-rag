# -*- coding: utf-8 -*-
"""noteDetail 페이지에서 다른 쪽지로 전환 탐색"""
import sys, json, urllib.request, time, sqlite3, base64
from pathlib import Path
from websocket import create_connection

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CDP_URL = "http://127.0.0.1:9000/json"
DB_PATH = Path(__file__).parent / "messages.db"

def js(ws, id_, expr):
    ws.send(json.dumps({"id": id_, "method": "Runtime.evaluate",
                        "params": {"expression": expr}}))
    return json.loads(ws.recv()).get("result", {}).get("result", {}).get("value", "")

def get_current_state(ws):
    r = js(ws, 99, """
    var noteCode = (document.querySelector('input[name*=code],input[name*=Code]') || {}).value || '';
    var files = document.querySelectorAll('.noteDownloadBtn[fileurl]');
    JSON.stringify({ note_code: noteCode, file_count: files.length })
    """)
    try: return json.loads(r)
    except: return {}

pages = json.loads(urllib.request.urlopen(CDP_URL, timeout=3).read())
note_page = next((p for p in pages if "noteDetail" in p.get("url", "")), None)
ws = create_connection(note_page["webSocketDebuggerUrl"], timeout=15)

current = get_current_state(ws)
print(f"현재 상태: {current}")

# DB에서 다른 파일 있는 쪽지
conn = sqlite3.connect(DB_PATH)
targets = conn.execute("SELECT note_code, title, file_cnt FROM notes WHERE file_cnt > 0 AND note_code != ? LIMIT 5",
                       (current.get('note_code',''),)).fetchall()
conn.close()
target = targets[0]
print(f"\n전환 목표: {target[1][:40]} (files={target[2]})")
target_code = target[0]

# noteDetail 페이지 내 모든 함수 목록
print("\n=== noteDetail 내 전체 함수 목록 ===")
r = js(ws, 1, """
JSON.stringify(Object.keys(window).filter(function(k){
    return typeof window[k]==='function' && !/^on|jQuery|_|\\$/.test(k);
}).slice(0,60))
""")
funcs = json.loads(r) if r else []
print(funcs)

# URL 네비게이션 시도
print("\n=== location.href 변경 시도 ===")
r2 = js(ws, 2, f"location.href")
print(f"현재 href: {r2}")

# noteDetail URL에 파라미터 붙여서 이동
print("\n=== noteDetail?noteCode= 로 이동 ===")
js(ws, 3, f"location.href = '/ezmaru/pc/noteDetail?noteCode={target_code}'")
time.sleep(3)

after = get_current_state(ws)
print(f"이동 후 상태: {after}")

if after.get('note_code') == target_code:
    print("✓ URL 파라미터로 전환 성공!")
else:
    print("URL 파라미터 방법 실패, 다른 방법 시도...")

    # Ajax로 noteDetail HTML 가져와서 교체하는 방법
    print("\n=== Ajax 로드 후 DOM 교체 시도 ===")
    r3 = js(ws, 10, f"""
    var r = '';
    $.ajax({{
        url: '/ezmaru/pc/noteDetail',
        type: 'GET',
        data: {{ noteCode: '{target_code}' }},
        async: false,
        success: function(html) {{ r = 'OK: len=' + html.length; }},
        error: function(e) {{ r = 'ERR:' + e.status; }}
    }});
    r
    """)
    print(r3)

# 현재 파일 URL들 전부 추출 (현재 열린 쪽지)
print("\n=== 현재 열린 쪽지 파일 전체 목록 ===")
r4 = js(ws, 20, """
var files = document.querySelectorAll('.noteDownloadBtn[fileurl]');
var noteCode = (document.querySelector('input[name*=code],input[name*=Code]') || {}).value || '';
JSON.stringify({
    note_code: noteCode,
    files: Array.from(files).map(function(el){
        var container = el.closest('li') || el.closest('div');
        var nameEl = container ? container.querySelector('[data-original-title]') : null;
        return {
            fileurl: el.getAttribute('fileurl'),
            oriname: el.getAttribute('oriname'),
            filename: nameEl ? nameEl.getAttribute('data-original-title') : ''
        };
    })
})
""")
try:
    data = json.loads(r4)
    print(f"note_code: {data['note_code']}")
    for f in data['files']:
        try:
            fname = base64.b64decode(f['oriname']).decode('utf-8')
        except:
            fname = f['oriname']
        print(f"  파일명: {f['filename'] or fname}")
        print(f"  URL: {f['fileurl'][:80]}...")
except:
    print(r4[:500])

ws.close()
