# -*- coding: utf-8 -*-
"""noteDetail URL 전환 후 WS 재연결 방식 - 파일 추출 완전 검증"""
import sys, json, urllib.request, time, sqlite3, base64
from pathlib import Path
from websocket import create_connection

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CDP_URL = "http://127.0.0.1:9000/json"
DB_PATH  = Path(__file__).parent / "messages.db"

def get_pages():
    return json.loads(urllib.request.urlopen(CDP_URL, timeout=3).read())

def get_note_ws():
    """현재 열린 noteDetail 페이지 WS URL 반환"""
    for p in get_pages():
        if "noteDetail" in p.get("url","") and "webSocketDebuggerUrl" in p:
            return p["webSocketDebuggerUrl"], p.get("url","")
    return None, None

def js(ws, id_, expr):
    ws.send(json.dumps({"id": id_, "method": "Runtime.evaluate",
                        "params": {"expression": expr}}))
    return json.loads(ws.recv()).get("result", {}).get("result", {}).get("value", "")

def navigate_to_note(note_code):
    """현재 noteDetail WS에 연결해서 다른 note_code로 이동, WS 재연결 반환"""
    ws_url, cur_url = get_note_ws()
    if not ws_url:
        return None
    ws = create_connection(ws_url, timeout=10)
    js(ws, 1, f"location.href = '/ezmaru/pc/noteDetail?noteCode={note_code}'")
    ws.close()

    # 페이지 이동 후 새 WS URL 기다리기 (최대 6초)
    for _ in range(12):
        time.sleep(0.5)
        ws_url2, url2 = get_note_ws()
        if ws_url2 and note_code in (url2 or ""):
            return ws_url2
    # URL에 noteCode 없어도 새 WS이면 반환
    ws_url2, _ = get_note_ws()
    return ws_url2

def extract_files_from_ws(ws_url):
    """WS에 연결해서 파일 정보 추출 (로딩 대기 포함)"""
    ws = create_connection(ws_url, timeout=15)
    # 페이지 완전 로딩 대기
    for _ in range(20):
        r = js(ws, 10, "document.readyState + '|' + (document.querySelector('.noteDownloadBtn') ? 'files' : 'nofile')")
        if "complete" in str(r):
            break
        time.sleep(0.5)

    r = js(ws, 11, """
    var noteCode = (document.querySelector('input[name*=code],input[name*=Code]') || {}).value || '';
    var titleEl = document.querySelector('h4,h3,[class*=title],[class*=subject]');
    var files = Array.from(document.querySelectorAll('.noteDownloadBtn[fileurl]')).map(function(el){
        var container = el.closest('li,tr') || el.parentElement;
        var nameEl = container ? (container.querySelector('[data-original-title]') || container.querySelector('.fileName')) : null;
        return {
            fileurl: el.getAttribute('fileurl') || '',
            oriname: el.getAttribute('oriname') || '',
            display_name: nameEl ? (nameEl.getAttribute('data-original-title') || nameEl.innerText.trim()) : ''
        };
    });
    JSON.stringify({note_code: noteCode, files: files})
    """)
    cookie = js(ws, 12, "document.cookie")
    ws.close()
    try:
        data = json.loads(r)
        data['cookie'] = cookie
        return data
    except:
        return {}

# DB에서 파일 있는 쪽지 (최대 5개 테스트)
conn = sqlite3.connect(DB_PATH)
notes = conn.execute("SELECT note_code, title, file_cnt FROM notes WHERE file_cnt > 0 LIMIT 5").fetchall()
conn.close()
print(f"테스트 대상: {len(notes)}건\n")

# 현재 WS에서 쿠키 먼저 추출
ws_url, _ = get_note_ws()
if ws_url:
    ws_tmp = create_connection(ws_url, timeout=10)
    cookie = js(ws_tmp, 1, "document.cookie")
    ws_tmp.close()
    print(f"쿠키 확인: {cookie[:80]}...\n")

all_results = []
for note_code, title, file_cnt in notes:
    print(f"=== {title[:40]} (files={file_cnt}) ===")

    ws_url2 = navigate_to_note(note_code)
    if not ws_url2:
        print("  WS 연결 실패, 건너뜀")
        continue

    # 추가 대기
    time.sleep(2)
    data = extract_files_from_ws(ws_url2)

    print(f"  note_code: {data.get('note_code','?')}")
    print(f"  파일 수: {len(data.get('files',[]))}")
    for f in data.get('files', []):
        try:
            fname = base64.b64decode(f['oriname']).decode('utf-8')
        except:
            fname = f.get('display_name', f['oriname'])
        print(f"  → {fname}")
        if f.get('fileurl'):
            # 다운로드 테스트
            try:
                url = f"{f['fileurl']}/{f['oriname']}"
                req = urllib.request.Request(url)
                req.add_header("Cookie", cookie)
                req.add_header("Referer", "http://stmsg.cbe.go.kr:7880/ezmaru/pc/noteDetail")
                req.add_header("User-Agent", "Mozilla/5.0")
                resp = urllib.request.urlopen(req, timeout=10)
                size = resp.headers.get('Content-Length', '?')
                ctype = resp.headers.get('Content-Type', '?')
                resp.read()
                print(f"     ✓ 다운로드 OK - {size} bytes [{ctype}]")
            except Exception as e:
                print(f"     ✗ 다운로드 실패: {e}")

    all_results.append({'note_code': note_code, 'files': data.get('files', [])})
    print()

print("=== 요약 ===")
total_files = sum(len(r['files']) for r in all_results)
print(f"확인된 파일: {total_files}개 / {len(notes)}개 쪽지")
