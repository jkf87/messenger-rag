# -*- coding: utf-8 -*-
"""배치 다운로드 5개 테스트"""
import sys, json, urllib.request, urllib.error, time, sqlite3, base64
from pathlib import Path
from websocket import create_connection

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CDP_URL  = "http://127.0.0.1:9000/json"
DB_PATH  = Path(__file__).parent / "messages.db"
SAVE_DIR = Path(__file__).parent / "attachments"
SAVE_DIR.mkdir(exist_ok=True)

def get_note_ws():
    pages = json.loads(urllib.request.urlopen(CDP_URL, timeout=3).read())
    for p in pages:
        if "noteDetail" in p.get("url","") and "webSocketDebuggerUrl" in p:
            return p["webSocketDebuggerUrl"]
    return None

def js(ws, id_, expr):
    ws.send(json.dumps({"id": id_, "method": "Runtime.evaluate",
                        "params": {"expression": expr}}))
    return json.loads(ws.recv()).get("result", {}).get("result", {}).get("value", "")

ws = create_connection(get_note_ws(), timeout=20)
cookie = js(ws, 1, "document.cookie")

conn = sqlite3.connect(DB_PATH)
notes = conn.execute("SELECT note_code, title, file_cnt FROM notes WHERE file_cnt > 0 LIMIT 10").fetchall()
conn.close()

for i, (note_code, title, file_cnt) in enumerate(notes):
    print(f"\n[{i+1}] {title[:40]} (파일{file_cnt}개)")

    # 쪽지 로드
    r = js(ws, 10+i, f"""
    try {{
        $('input[name=code]').val('{note_code}');
        noteDetail_controller.noteDetail();
        'ok'
    }} catch(e) {{ 'err:' + e.message }}
    """)
    print(f"  로드: {r}")
    time.sleep(3)

    # 현재 DOM 상태
    state = js(ws, 100+i, """
    var code = $('input[name=code]').val();
    var files = Array.from(document.querySelectorAll('[fileurl]')).filter(function(el){
        return (el.getAttribute('fileurl')||'').includes('/upload/note/');
    }).map(function(el){
        try { return atob(el.getAttribute('oriname')); } catch(e) { return el.getAttribute('oriname'); }
    });
    var seen = {}, uniq = [];
    files.forEach(function(f){ if(!seen[f]){ seen[f]=1; uniq.push(f); } });
    JSON.stringify({code: code, files: uniq})
    """)
    try:
        data = json.loads(state)
        print(f"  code={data['code'][:16]}..., 파일: {data['files']}")
    except:
        print(f"  상태: {state[:200]}")

ws.close()
