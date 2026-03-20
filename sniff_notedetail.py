# -*- coding: utf-8 -*-
"""noteDetail 페이지 네트워크 + DOM 스니핑"""
import sys, json, urllib.request, time
from websocket import create_connection

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CDP_URL = "http://127.0.0.1:9000/json"

def js(ws, id_, expr):
    ws.send(json.dumps({"id": id_, "method": "Runtime.evaluate",
                        "params": {"expression": expr}}))
    return json.loads(ws.recv()).get("result", {}).get("result", {}).get("value", "")

pages = json.loads(urllib.request.urlopen(CDP_URL, timeout=3).read())

# noteDetail 페이지 찾기
note_page = next((p for p in pages if "noteDetail" in p.get("url", "")), None)
if not note_page:
    print("noteDetail 페이지가 열려있지 않습니다. 메신저에서 쪽지를 먼저 열어주세요.")
    exit(1)

print(f"noteDetail 페이지 발견: {note_page['url']}")
ws = create_connection(note_page["webSocketDebuggerUrl"], timeout=15)

# 1. 현재 페이지 DOM에서 파일 관련 정보 추출
print("\n=== DOM에서 파일 정보 추출 ===")

# 첨부파일 링크/버튼 찾기
r = js(ws, 1, """
var result = {};
// 파일 관련 요소들
var fileEls = document.querySelectorAll('[class*=file],[class*=attach],[onclick*=file],[onclick*=down],[href*=file],[href*=down]');
result.fileElements = Array.from(fileEls).map(function(el){
    return {
        tag: el.tagName,
        cls: el.className,
        onclick: el.getAttribute('onclick') || '',
        href: el.getAttribute('href') || '',
        text: el.innerText.trim().substring(0,50)
    };
});
// 모든 onclick 속성
var allOnclick = document.querySelectorAll('[onclick]');
result.onclicks = Array.from(allOnclick).slice(0,30).map(function(el){
    return { tag: el.tagName, cls: el.className.substring(0,30), onclick: el.getAttribute('onclick'), text: el.innerText.trim().substring(0,30) };
});
JSON.stringify(result)
""")
try:
    parsed = json.loads(r)
    print("파일 관련 요소:")
    for el in parsed.get("fileElements", []):
        print(f"  {el}")
    print("\n모든 onclick:")
    for el in parsed.get("onclicks", []):
        print(f"  {el}")
except:
    print(r[:500])

# 2. 페이지 전체 HTML (간략)
print("\n=== 페이지 title + 파일 영역 HTML ===")
r2 = js(ws, 2, """
var t = document.title + ' | ';
var fileArea = document.querySelector('.file_area,.attach_area,.fileList,.attachList,[class*=file_list]');
t += fileArea ? fileArea.outerHTML.substring(0,800) : '파일영역 없음';
t
""")
print(r2)

# 3. 네트워크 캡처하면서 파일 클릭 유도
ws.send(json.dumps({"id": 10, "method": "Network.enable"}))
ws.recv()
print("\n=== 네트워크 캡처 시작 (20초) ===")
print("첨부파일을 클릭해보세요!")

body_pending = {}
start = time.time()
while time.time() - start < 20:
    try:
        ws.settimeout(1)
        msg = json.loads(ws.recv())
        method = msg.get("method", "")

        if method == "Network.requestWillBeSent":
            p = msg["params"]
            req = p.get("request", {})
            url = req.get("url", "")
            rid = p.get("requestId", "")
            data = req.get("postData", "")
            body_pending[rid] = url
            print(f"\n→ {url}")
            if data: print(f"   DATA: {data[:200]}")

        elif method == "Network.responseReceived":
            rid    = msg["params"].get("requestId", "")
            status = msg["params"].get("response", {}).get("status", "")
            url    = msg["params"].get("response", {}).get("url", "")
            if rid in body_pending:
                print(f"← [{status}] {url}")
                ws.send(json.dumps({"id": 300, "method": "Network.getResponseBody",
                                    "params": {"requestId": rid}}))

        elif msg.get("id") == 300:
            body = msg.get("result", {}).get("body", "")
            if body: print(f"   BODY: {body[:600]}")

    except: pass

ws.close()
print("\n완료")
