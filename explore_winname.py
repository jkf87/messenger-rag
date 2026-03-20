# -*- coding: utf-8 -*-
"""window.name 방식으로 noteDetail 쪽지 전환 시도"""
import sys, json, urllib.request, time, sqlite3, base64
from pathlib import Path
from websocket import create_connection

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CDP_URL = "http://127.0.0.1:9000/json"
DB_PATH  = Path(__file__).parent / "messages.db"

def get_pages():
    return json.loads(urllib.request.urlopen(CDP_URL, timeout=3).read())

def js(ws, id_, expr):
    ws.send(json.dumps({"id": id_, "method": "Runtime.evaluate",
                        "params": {"expression": expr}}))
    return json.loads(ws.recv()).get("result", {}).get("result", {}).get("value", "")

pages = get_pages()
note_page = next((p for p in pages if "noteDetail" in p.get("url","") and "webSocketDebuggerUrl" in p), None)
ws = create_connection(note_page["webSocketDebuggerUrl"], timeout=15)

# 현재 상태 확인
print("=== 현재 noteDetail 상태 ===")
r = js(ws, 1, """
JSON.stringify({
    window_name: window.name,
    current_code: (document.querySelector('input[name=code]') || {}).value || '',
    file_count: document.querySelectorAll('[fileurl]').length,
    url: location.href
})
""")
print(r)

# 초기화 관련 함수 찾기
print("\n=== 초기화/로드 관련 함수 ===")
r2 = js(ws, 2, """
var found = [];
// init, load, view 관련 전역 함수
['noteInit','initNote','viewNote','loadNote','showNote','openNote',
 'noteViewInit','initNoteView','noteDetailInit','initNoteDetail',
 'init','pageInit','onLoad','pageLoad'].forEach(function(name){
    if(typeof window[name] === 'function') found.push(name);
});
JSON.stringify(found)
""")
print(r2)

# inline script에서 로드 함수 찾기
print("\n=== inline script에서 init 패턴 ===")
r3 = js(ws, 3, """
var scripts = Array.from(document.querySelectorAll('script:not([src])')).map(function(s){
    return s.textContent;
}).join('\\n');
// init, window.name, code 관련 부분 추출 (각 200자)
var patterns = [
    /window\\.name[^;]{0,100}/g,
    /input\\[name=[^]]{0,50}code[^)]{0,50}/g,
    /function\\s+(?:init|load|view)[^(]{0,20}\\([^)]{0,50}\\)[^{]{0,20}\\{[^}]{0,200}/gi
];
var results = [];
patterns.forEach(function(p){
    var m;
    while((m = p.exec(scripts)) !== null) results.push(m[0]);
});
JSON.stringify(results.slice(0,10))
""")
try:
    items = json.loads(r3)
    for item in items:
        print(item)
except:
    print(r3[:500])

# window.name 변경 + 새로고침으로 다른 쪽지 로드 시도
conn = sqlite3.connect(DB_PATH)
targets = conn.execute("SELECT note_code, title FROM notes WHERE file_cnt > 0 LIMIT 5").fetchall()
conn.close()

current_code = json.loads(r).get('current_code', '')
target = next((t for t in targets if t[0] != current_code), None)
if target:
    target_code, target_title = target
    print(f"\n=== window.name 변경으로 전환 시도: {target_title[:30]} ===")
    # window.name 변경
    r4 = js(ws, 10, f"""
    var old_name = window.name;
    window.name = 'viewnote:{target_code}';
    old_name + ' -> ' + window.name
    """)
    print(f"window.name 변경: {r4}")

    # 찾을 수 있는 init 함수 호출
    r5 = js(ws, 11, """
    var called = [];
    ['noteInit','initNote','pageInit','init'].forEach(function(fn){
        if(typeof window[fn] === 'function') {
            try { window[fn](); called.push(fn + ':ok'); } catch(e) { called.push(fn + ':err-' + e.message); }
        }
    });
    called.join(', ') || '호출 가능 함수 없음'
    """)
    print(f"init 호출: {r5}")
    time.sleep(3)

    # 상태 확인
    r6 = js(ws, 12, """
    JSON.stringify({
        code: (document.querySelector('input[name=code]') || {}).value,
        files: document.querySelectorAll('[fileurl]').length
    })
    """)
    print(f"변경 후 상태: {r6}")

    # location.reload() 로 전환
    print("\n=== location.reload() + window.name 조합 ===")
    js(ws, 20, f"window.name = 'viewnote:{target_code}'; location.reload();")
    # ws 끊김 - 재연결
    ws.close()

    time.sleep(3)
    pages2 = get_pages()
    note_page2 = next((p for p in pages2 if "noteDetail" in p.get("url","") and "webSocketDebuggerUrl" in p), None)
    if note_page2:
        ws2 = create_connection(note_page2["webSocketDebuggerUrl"], timeout=15)
        time.sleep(3)  # 로딩 대기
        r7 = js(ws2, 1, """
        JSON.stringify({
            window_name: window.name,
            code: (document.querySelector('input[name=code]') || {}).value || '',
            files: document.querySelectorAll('[fileurl]').length,
            file_info: Array.from(document.querySelectorAll('[fileurl]')).map(function(el){
                return {oriname: el.getAttribute('oriname'), url_part: (el.getAttribute('fileurl')||'').slice(-40)};
            })
        })
        """)
        print(f"reload 후 상태: {r7}")
        ws2.close()

print("\n완료")
