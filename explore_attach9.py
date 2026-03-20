# -*- coding: utf-8 -*-
"""noteDetail URL 파라미터로 쪽지 전환 + 파일 추출 완전 검증"""
import sys, json, urllib.request, time, sqlite3, base64
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

def wait_for_note(ws, expected_code, timeout=10):
    """쪽지 페이지 로딩 완료까지 대기"""
    start = time.time()
    while time.time() - start < timeout:
        r = js(ws, 998, """
        var code = (document.querySelector('input[name*=code],input[name*=Code]') || {}).value || '';
        var files = document.querySelectorAll('.noteDownloadBtn[fileurl]');
        JSON.stringify({code: code, files: files.length, ready: document.readyState})
        """)
        try:
            state = json.loads(r)
            if state.get('code') == expected_code and state.get('files', 0) >= 0:
                return state
        except:
            pass
        time.sleep(0.5)
    return {}

def extract_files(ws):
    """현재 페이지 파일 목록 추출"""
    r = js(ws, 999, """
    var noteCode = (document.querySelector('input[name*=code],input[name*=Code]') || {}).value || '';
    var titleEl = document.querySelector('.noteTitle,.note_title,[class*=noteTitle],.noteSubject');
    var noteTitle = titleEl ? titleEl.innerText.trim() : '';
    var files = Array.from(document.querySelectorAll('.noteDownloadBtn[fileurl]')).map(function(el){
        var container = el.closest('li,tr') || el.parentElement;
        var nameEl = container ? (container.querySelector('[data-original-title]') || container.querySelector('.fileName,.file_name')) : null;
        var oriname = el.getAttribute('oriname') || '';
        return {
            fileurl: el.getAttribute('fileurl') || '',
            oriname: oriname,
            display_name: nameEl ? (nameEl.getAttribute('data-original-title') || nameEl.innerText.trim()) : ''
        };
    });
    JSON.stringify({note_code: noteCode, note_title: noteTitle, files: files})
    """)
    try:
        return json.loads(r)
    except:
        return {}

# DB에서 파일 있는 쪽지 목록
conn = sqlite3.connect(DB_PATH)
notes_with_files = conn.execute(
    "SELECT note_code, title, file_cnt FROM notes WHERE file_cnt > 0 LIMIT 5"
).fetchall()
conn.close()

print(f"파일 있는 쪽지: {len(notes_with_files)}건 (테스트: 5건)")

pages = json.loads(urllib.request.urlopen(CDP_URL, timeout=3).read())
note_page = next((p for p in pages if "noteDetail" in p.get("url","") and "webSocketDebuggerUrl" in p), None)
ws = create_connection(note_page["webSocketDebuggerUrl"], timeout=15)

# 각 쪽지로 순서대로 이동하며 파일 정보 추출
results = []
for note_code, title, file_cnt in notes_with_files:
    print(f"\n{'='*50}")
    print(f"쪽지: {title[:40]}  (files={file_cnt})")

    # URL 변경으로 해당 쪽지 로드
    js(ws, 1, f"location.href = '/ezmaru/pc/noteDetail?noteCode={note_code}'")

    # 로딩 대기 (최대 8초)
    state = wait_for_note(ws, note_code, timeout=8)
    print(f"  로딩 상태: code={state.get('code','?')}, files={state.get('files','?')}, ready={state.get('ready','?')}")

    if state.get('code') != note_code:
        # 조금 더 대기
        time.sleep(2)
        state = wait_for_note(ws, note_code, timeout=5)
        print(f"  재시도 후: {state}")

    # 파일 정보 추출
    data = extract_files(ws)
    print(f"  추출된 파일 수: {len(data.get('files',[]))}")

    for f in data.get('files', []):
        try:
            fname = base64.b64decode(f['oriname']).decode('utf-8')
        except:
            fname = f.get('display_name', f.get('oriname','?'))
        print(f"  → {fname}")
        print(f"     URL: {f['fileurl'][:80]}...")

    results.append({
        'note_code': note_code,
        'title': title,
        'files': data.get('files', [])
    })

# 쿠키 가져오기
cookie = js(ws, 900, "document.cookie")
print(f"\n=== 쿠키 (다운로드에 사용) ===")
print(cookie[:200])

# 첫 번째 파일 다운로드 테스트
print("\n=== 다운로드 테스트 ===")
for result in results:
    for f in result['files']:
        if f.get('fileurl'):
            try:
                fname = base64.b64decode(f['oriname']).decode('utf-8')
            except:
                fname = f.get('display_name', 'unknown')
            url = f"{f['fileurl']}/{f['oriname']}"
            req = urllib.request.Request(url)
            req.add_header("Cookie", cookie)
            req.add_header("Referer", "http://stmsg.cbe.go.kr:7880/ezmaru/pc/noteDetail")
            req.add_header("User-Agent", "Mozilla/5.0")
            try:
                resp = urllib.request.urlopen(req, timeout=10)
                size = int(resp.headers.get('Content-Length', 0))
                ctype = resp.headers.get('Content-Type', '?')
                print(f"✓ {fname} - {size:,} bytes  [{ctype}]")
                resp.read()  # 읽고 닫기
            except Exception as e:
                print(f"✗ {fname} - 오류: {e}")
            break
    break

ws.close()
print("\n탐색 완료")
