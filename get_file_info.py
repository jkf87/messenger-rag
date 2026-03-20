# -*- coding: utf-8 -*-
"""noteDetail 페이지에서 파일 코드 및 다운로드 URL 추출"""
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
note_page = next((p for p in pages if "noteDetail" in p.get("url", "")), None)
if not note_page:
    print("noteDetail 페이지 없음 - 메신저에서 쪽지를 열어주세요")
    exit(1)

ws = create_connection(note_page["webSocketDebuggerUrl"], timeout=15)

# 1. 파일 영역 전체 HTML
print("=== 파일 관련 전체 HTML ===")
r = js(ws, 1, """
var areas = document.querySelectorAll('.fileArea,.file_area,.fileList,.attachWrap,.noteFileWrap,.noteAttach,[class*=noteFile],[class*=attachFile]');
var result = Array.from(areas).map(function(el){ return el.outerHTML; }).join('\\n---\\n');
result || '없음'
""")
print(r[:2000])

# 2. 파일 다운로드 버튼 주변 HTML
print("\n=== noteDownloadBtn 주변 HTML ===")
r2 = js(ws, 2, """
var btns = document.querySelectorAll('.noteDownloadBtn, [class*=download], [class*=Download]');
JSON.stringify(Array.from(btns).map(function(el){
    return {
        cls: el.className,
        text: el.innerText.trim(),
        parent: el.parentElement ? el.parentElement.outerHTML.substring(0,400) : '',
        dataset: JSON.stringify(el.dataset),
        attrs: Array.from(el.attributes).map(function(a){ return a.name+'='+a.value; })
    };
}))
""")
try:
    items = json.loads(r2)
    for item in items:
        print(f"class: {item['cls']}")
        print(f"text: {item['text']}")
        print(f"dataset: {item['dataset']}")
        print(f"attrs: {item['attrs']}")
        print(f"parent HTML:\n{item['parent']}")
        print("---")
except:
    print(r2[:1000])

# 3. 전역 JS 변수에서 파일 정보 찾기
print("\n=== 전역 변수에서 파일 정보 ===")
r3 = js(ws, 3, """
var result = {};
// 일반적으로 쪽지 상세 페이지는 noteInfo, noteData 같은 변수 사용
var candidates = ['noteInfo','noteData','noteDetail','fileList','attachList','noteFileList','viewData','pageData'];
candidates.forEach(function(name){
    try { if(window[name]) result[name] = JSON.stringify(window[name]).substring(0,300); } catch(e){}
});
JSON.stringify(result)
""")
try:
    parsed = json.loads(r3)
    for k, v in parsed.items():
        print(f"window.{k}: {v}")
except:
    print(r3[:500])

# 4. 페이지 URL 파라미터
print("\n=== 현재 URL + 파라미터 ===")
r4 = js(ws, 4, "JSON.stringify({href: location.href, search: location.search, hash: location.hash})")
print(r4)

# 5. img src 에서 파일 코드 추출 (썸네일 URL에 파일 코드가 있을 수 있음)
print("\n=== 첨부 이미지 src ===")
r5 = js(ws, 5, """
var imgs = document.querySelectorAll('.attachExistImg, [class*=attachImg]');
JSON.stringify(Array.from(imgs).map(function(el){
    return { src: el.src || el.getAttribute('data-src') || el.getAttribute('data-original'), cls: el.className };
}))
""")
try:
    items = json.loads(r5)
    for item in items:
        print(f"  src={item['src']}  cls={item['cls'][:40]}")
except:
    print(r5[:500])

# 6. noteDownloadBtn 클릭 시 실제 호출 함수 찾기 (이벤트 리스너)
print("\n=== 다운로드 관련 JS 함수 검색 ===")
r6 = js(ws, 6, """
var scripts = Array.from(document.querySelectorAll('script')).map(function(s){ return s.src || 'inline'; });
// 전역 함수 중 file/down/attach 관련
var funcs = Object.keys(window).filter(function(k){
    return /file|down|attach|note.*file|file.*note/i.test(k) && typeof window[k] === 'function';
});
JSON.stringify({scripts: scripts.slice(0,10), funcs: funcs.slice(0,20)})
""")
try:
    parsed = json.loads(r6)
    print("Scripts:", parsed.get("scripts", []))
    print("File-related functions:", parsed.get("funcs", []))
except:
    print(r6[:500])

# 7. 네트워크 캡처하면서 저장 버튼 클릭
print("\n=== 저장 버튼 자동 클릭 + 네트워크 캡처 ===")
ws.send(json.dumps({"id": 10, "method": "Network.enable"}))
ws.recv()

# 저장 버튼 클릭
click_result = js(ws, 11, """
var btn = document.querySelector('.noteDownloadBtn');
if(btn) { btn.click(); 'clicked: ' + btn.className; }
else { 'not found'; }
""")
print(f"클릭 결과: {click_result}")

start = time.time()
while time.time() - start < 8:
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
            print(f"\n→ {url}")
            if data: print(f"   DATA: {data[:300]}")
        elif method == "Network.responseReceived":
            url    = msg["params"].get("response", {}).get("url", "")
            status = msg["params"].get("response", {}).get("status", "")
            rid    = msg["params"].get("requestId", "")
            print(f"← [{status}] {url}")
            ws.send(json.dumps({"id": 400, "method": "Network.getResponseBody",
                                "params": {"requestId": rid}}))
        elif msg.get("id") == 400:
            body = msg.get("result", {}).get("body", "")
            if body: print(f"   BODY: {body[:400]}")
    except: pass

ws.close()
