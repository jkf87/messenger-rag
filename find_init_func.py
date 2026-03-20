# -*- coding: utf-8 -*-
"""noteDetail compiled JS에서 초기화/파일 로드 함수 탐색"""
import sys, json, urllib.request, re, time
from websocket import create_connection

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CDP_URL = "http://127.0.0.1:9000/json"
BASE    = "http://stmsg.cbe.go.kr:7880"

def get_pages():
    return json.loads(urllib.request.urlopen(CDP_URL, timeout=3).read())

def js(ws, id_, expr):
    ws.send(json.dumps({"id": id_, "method": "Runtime.evaluate",
                        "params": {"expression": expr}}))
    return json.loads(ws.recv()).get("result", {}).get("result", {}).get("value", "")

pages = get_pages()
note_page = next((p for p in pages if "noteDetail" in p.get("url","") and "webSocketDebuggerUrl" in p), None)
ws_note = create_connection(note_page["webSocketDebuggerUrl"], timeout=15)

# 1. 현재 쿠키
cookie = js(ws_note, 1, "document.cookie")

# 2. 로드된 JS 파일 목록
print("=== 로드된 JS 파일 ===")
r = js(ws_note, 2, """
JSON.stringify(Array.from(document.querySelectorAll('script[src]')).map(function(s){ return s.src; }))
""")
scripts = json.loads(r)
for s in scripts:
    print(f"  {s}")

# 3. compiled.js 가져와서 파일/note 관련 함수 검색
print("\n=== compiled.js 분석 ===")
compiled_url = next((s for s in scripts if "compiled" in s), None)
if compiled_url:
    req = urllib.request.Request(compiled_url)
    req.add_header("Cookie", cookie)
    src = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", errors="replace")
    print(f"크기: {len(src):,} chars")

    # fileurl, oriname, upload/note 관련 코드 찾기
    patterns = [
        (r'.{0,80}fileurl.{0,80}', "fileurl"),
        (r'.{0,80}oriname.{0,80}', "oriname"),
        (r'.{0,80}upload/note.{0,80}', "upload/note"),
        (r'.{0,80}noteDetail.{0,80}', "noteDetail"),
        (r'.{0,80}NTE_CODE.{0,80}', "NTE_CODE"),
        (r'function\s+\w*[Ff]ile\w*\s*\([^)]*\)', "file functions"),
        (r'function\s+\w*[Nn]ote\w*\s*\([^)]*\)', "note functions"),
    ]
    for pattern, label in patterns:
        matches = re.findall(pattern, src)
        if matches:
            print(f"\n[{label}] ({len(matches)}개):")
            for m in matches[:3]:
                print(f"  {m.strip()[:120]}")

# 4. about:blank에서 main 창 접근 시도
print("\n=== about:blank WS에서 main 접근 ===")
blank_page = next((p for p in pages if "about:blank" in p.get("url","") and "webSocketDebuggerUrl" in p), None)
if blank_page:
    ws_blank = create_connection(blank_page["webSocketDebuggerUrl"], timeout=10)

    # main 창 찾기
    r2 = js(ws_blank, 10, """
    var wins = [];
    try {
        // opener 체인
        if(window.opener) wins.push('has_opener: ' + window.opener.location.href);
        // frames
        wins.push('frames: ' + window.frames.length);
        // 창 목록
        wins.push('name: ' + window.name);
    } catch(e) { wins.push('err: ' + e.message); }
    JSON.stringify(wins)
    """)
    print(f"about:blank 접근: {r2}")
    ws_blank.close()

# 5. XHR intercept 후 dummy 페이지 이동으로 init 재현
print("\n=== noteDetail init 재현 시도 ===")
# XHR 캡처 설정
js(ws_note, 20, """
window._xhrLog = [];
var _origOpen = XMLHttpRequest.prototype.open;
XMLHttpRequest.prototype.open = function(method, url) {
    this._url = url;
    return _origOpen.apply(this, arguments);
};
var _origSend = XMLHttpRequest.prototype.send;
XMLHttpRequest.prototype.send = function(body) {
    var self = this;
    this.addEventListener('load', function() {
        window._xhrLog.push({url: self._url, body: (body||'').substring(0,100), resp: self.responseText.substring(0,100)});
    });
    return _origSend.apply(this, arguments);
};
'XHR 캡처 설정'
""")

# 잠시 대기 후 로그 확인 (기존 polling AJAX 등 캡처)
time.sleep(3)
r3 = js(ws_note, 21, "JSON.stringify(window._xhrLog.slice(-10))")
try:
    logs = json.loads(r3)
    print(f"최근 XHR 요청 {len(logs)}건:")
    for log in logs:
        print(f"  URL: {log['url']}")
        if log.get('body'): print(f"  BODY: {log['body'][:80]}")
        if log.get('resp'): print(f"  RESP: {log['resp'][:80]}")
except:
    print(r3[:300])

ws_note.close()
