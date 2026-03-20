# -*- coding: utf-8 -*-
"""파일 다운로드 전체 파이프라인 탐색"""
import sys, json, urllib.request, urllib.error, base64
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
    print("noteDetail 없음")
    exit(1)

ws = create_connection(note_page["webSocketDebuggerUrl"], timeout=15)

# 1. 현재 열린 쪽지의 모든 파일 정보 추출
print("=== 현재 쪽지 파일 목록 ===")
r = js(ws, 1, """
var files = document.querySelectorAll('.noteDownloadBtn[fileurl]');
JSON.stringify(Array.from(files).map(function(el){
    var fileurl = el.getAttribute('fileurl');
    var oriname = el.getAttribute('oriname');
    var fname = el.closest('[data-original-title]') || el.parentElement.querySelector('[data-original-title]');
    return {
        fileurl: fileurl,
        oriname: oriname,
        display_name: fname ? fname.getAttribute('data-original-title') : ''
    };
}))
""")
try:
    files = json.loads(r)
    for f in files:
        print(f"  fileurl: {f['fileurl']}")
        print(f"  oriname: {f['oriname']}")
        try:
            decoded = base64.b64decode(f['oriname']).decode('utf-8')
            print(f"  oriname decoded: {decoded}")
        except:
            pass
        print(f"  display: {f['display_name']}")
        print()
except:
    print(r[:500])

# 2. 쿠키 가져오기 (다운로드에 필요)
print("=== 쿠키 ===")
r2 = js(ws, 2, "document.cookie")
print(r2[:300])

# 3. noteDetail JS 함수로 다른 쪽지 불러오는 방법 탐색
print("\n=== 쪽지 전환 함수 탐색 ===")
r3 = js(ws, 3, """
var funcs = Object.keys(window).filter(function(k){
    return /note|view|detail|load/i.test(k) && typeof window[k] === 'function';
}).slice(0,30);
JSON.stringify(funcs)
""")
print(r3)

# 4. noteDetail 전역 객체 전체 키 확인
print("\n=== window.noteDetail 구조 ===")
r4 = js(ws, 4, """
if(window.noteDetail) {
    JSON.stringify(Object.keys(window.noteDetail))
} else { 'undefined' }
""")
print(r4)

# 5. 현재 쪽지 NTE_CODE 확인
print("\n=== 현재 쪽지 코드 ===")
r5 = js(ws, 5, """
// URL 파라미터 또는 데이터 속성에서 찾기
var code = '';
var noteEl = document.querySelector('[note-code],[data-code],[noteCode],[id*=noteCode]');
if(noteEl) code = noteEl.getAttribute('note-code') || noteEl.getAttribute('data-code') || noteEl.value || '';
// hidden input
var hidden = document.querySelector('input[name*=code],input[name*=Code]');
if(hidden) code += ' | hidden:' + hidden.value;
// jQuery data
try {
    var jdata = $('[data-notecode]').first();
    if(jdata.length) code += ' | jdata:' + jdata.attr('data-notecode');
} catch(e){}
code || '직접 찾지 못함'
""")
print(r5)

# 6. 실제 파일 다운로드 테스트 (Python으로)
print("\n=== Python 다운로드 테스트 ===")
# 파일이 있으면 첫 번째 파일 다운로드
try:
    files_data = json.loads(r)
    if files_data and files_data[0].get('fileurl'):
        f = files_data[0]
        fileurl = f['fileurl']
        oriname = f['oriname']
        download_url = f"{fileurl}/{oriname}"
        cookie = r2

        print(f"다운로드 URL: {download_url[:100]}...")

        # 쿠키 포함 요청
        req = urllib.request.Request(download_url)
        req.add_header("Cookie", cookie)
        req.add_header("Referer", "http://stmsg.cbe.go.kr:7880/ezmaru/pc/noteDetail")
        req.add_header("User-Agent", "Mozilla/5.0")

        try:
            resp = urllib.request.urlopen(req, timeout=10)
            content = resp.read(1024)  # 처음 1KB만
            headers = dict(resp.headers)
            print(f"상태: 200 OK")
            print(f"Content-Type: {headers.get('Content-Type','?')}")
            print(f"Content-Length: {headers.get('Content-Length','?')}")
            print(f"Content-Disposition: {headers.get('Content-Disposition','?')}")
            print(f"다운로드 가능! 첫 {len(content)} bytes 수신")
        except urllib.error.HTTPError as e:
            print(f"HTTP Error: {e.code} {e.reason}")
        except Exception as e:
            print(f"Error: {e}")
except Exception as e:
    print(f"파일 정보 파싱 실패: {e}")

ws.close()
