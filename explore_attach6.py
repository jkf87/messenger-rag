# -*- coding: utf-8 -*-
"""noteDetail 페이지를 다른 쪽지로 전환하는 방법 탐색"""
import sys, json, urllib.request, time, sqlite3
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

def get_note_files(ws, id_base):
    """현재 noteDetail 페이지에서 파일 목록 추출"""
    r = js(ws, id_base, """
    var files = document.querySelectorAll('.noteDownloadBtn[fileurl]');
    var noteCode = (document.querySelector('input[name*=code],input[name*=Code]') || {}).value || '';
    JSON.stringify({
        note_code: noteCode,
        files: Array.from(files).map(function(el){
            return {
                fileurl: el.getAttribute('fileurl'),
                oriname: el.getAttribute('oriname')
            };
        })
    })
    """)
    try:
        return json.loads(r)
    except:
        return {"note_code": "", "files": []}

pages = json.loads(urllib.request.urlopen(CDP_URL, timeout=3).read())
note_page = next((p for p in pages if "noteDetail" in p.get("url", "")), None)
main_page = next((p for p in pages if "main" in p.get("url", "")), None)

if not note_page:
    print("noteDetail 없음")
    exit(1)

ws_note = create_connection(note_page["webSocketDebuggerUrl"], timeout=15)
ws_main = create_connection(main_page["webSocketDebuggerUrl"], timeout=15)

# 현재 파일 확인
current = get_note_files(ws_note, 1)
print(f"현재 쪽지: {current['note_code']}, 파일 수: {len(current['files'])}")

# 다른 note_code로 전환 시도 - main 페이지에서 쪽지 열기 함수 탐색
print("\n=== main 페이지에서 쪽지 열기 함수 ===")
r = js(ws_main, 10, """
var funcs = Object.keys(window).filter(function(k){
    return /note.*view|view.*note|note.*open|open.*note|noteDetail|note.*load/i.test(k) && typeof window[k] === 'function';
});
JSON.stringify(funcs)
""")
print("main 함수:", r)

# noteDetail 페이지 자체에서 다른 쪽지 로드 함수
print("\n=== noteDetail 페이지 로드 함수 ===")
r2 = js(ws_note, 11, """
var funcs = Object.keys(window).filter(function(k){
    return typeof window[k] === 'function';
}).filter(function(k){
    return /load|init|view|open|change|note/i.test(k);
}).slice(0,40);
JSON.stringify(funcs)
""")
print(r2)

# DB에서 파일 있는 다른 쪽지 코드
conn = sqlite3.connect(DB_PATH)
rows = conn.execute("SELECT note_code, title FROM notes WHERE file_cnt > 0 AND note_code != ? LIMIT 3",
                    (current['note_code'],)).fetchall()
conn.close()
target_code = rows[0][0] if rows else None
print(f"\n전환 대상 note_code: {target_code} ({rows[0][1][:30] if rows else '없음'})")

if target_code:
    # 방법 1: main 페이지에서 noteDetailView 호출
    print("\n=== 방법1: main에서 noteDetailView 호출 ===")
    r3 = js(ws_main, 20, f"""
    var result = '';
    try {{
        if(typeof noteDetailView === 'function') {{ noteDetailView('{target_code}'); result = 'noteDetailView called'; }}
        else if(typeof openNoteDetail === 'function') {{ openNoteDetail('{target_code}'); result = 'openNoteDetail called'; }}
        else if(typeof noteView === 'function') {{ noteView('{target_code}'); result = 'noteView called'; }}
        else {{ result = '함수 없음'; }}
    }} catch(e) {{ result = 'error: ' + e.message; }}
    result
    """)
    print(f"결과: {r3}")
    time.sleep(2)

    # 방법 2: noteDetail 페이지에서 직접 로드
    print("\n=== 방법2: noteDetail에서 직접 로드 ===")
    r4 = js(ws_note, 21, f"""
    var result = '';
    try {{
        if(typeof loadNoteDetail === 'function') {{ loadNoteDetail('{target_code}'); result = 'loadNoteDetail'; }}
        else if(typeof noteDetailLoad === 'function') {{ noteDetailLoad('{target_code}'); result = 'noteDetailLoad'; }}
        else if(typeof initNoteDetail === 'function') {{ initNoteDetail('{target_code}'); result = 'initNoteDetail'; }}
        else {{ result = '함수 없음'; }}
    }} catch(e) {{ result = 'error: ' + e.message; }}
    result
    """)
    print(f"결과: {r4}")
    time.sleep(2)

    # 방법 3: Ajax로 직접 noteDetail 로드
    print("\n=== 방법3: noteDetail ajax 직접 호출 ===")
    r5 = js(ws_note, 22, f"""
    var r = '';
    $.ajax({{
        url: '/ezmaru/pc/note/noteDetail',
        type: 'POST', async: false,
        data: {{ note_code: '{target_code}' }},
        success: function(d) {{ r = JSON.stringify(d).substring(0, 500); }},
        error: function(e) {{ r = 'ERR:' + e.status; }}
    }});
    r
    """)
    print(f"결과: {r5}")

    # 전환 후 파일 다시 확인
    after = get_note_files(ws_note, 30)
    print(f"\n전환 후 쪽지: {after['note_code']}, 파일 수: {len(after['files'])}")
    if after['note_code'] != current['note_code']:
        print("성공! 쪽지 전환됨")
        for f in after['files']:
            print(f"  {f}")
    else:
        print("쪽지 전환 안됨 (같은 쪽지)")

ws_note.close()
ws_main.close()
