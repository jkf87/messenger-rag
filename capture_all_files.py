# -*- coding: utf-8 -*-
"""
쪽지 첨부파일 전체 수집기
- noteDetail 페이지의 네트워크 + DOM을 모니터링
- 사용자가 쪽지를 클릭할 때마다 파일 URL 자동 포착
- 포착된 URL을 즉시 다운로드
사용법:
  1. 이 스크립트 실행
  2. 메신저에서 첨부파일 있는 쪽지를 하나씩 클릭
  3. Ctrl+C 로 종료
"""
import sys, json, urllib.request, urllib.error, time, sqlite3, base64
from pathlib import Path
from websocket import create_connection, WebSocketConnectionClosedException

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CDP_URL   = "http://127.0.0.1:9000/json"
DB_PATH   = Path(__file__).parent / "messages.db"
SAVE_DIR  = Path(__file__).parent / "attachments"

def get_pages():
    return json.loads(urllib.request.urlopen(CDP_URL, timeout=3).read())

def get_note_page():
    for p in get_pages():
        if "noteDetail" in p.get("url","") and "webSocketDebuggerUrl" in p:
            return p
    return None

def js(ws, id_, expr):
    ws.send(json.dumps({"id": id_, "method": "Runtime.evaluate",
                        "params": {"expression": expr}}))
    return json.loads(ws.recv()).get("result", {}).get("result", {}).get("value", "")

def extract_files_from_dom(ws):
    """현재 DOM에서 파일 정보 + 쪽지 코드 추출"""
    r = js(ws, 9001, """
    var code = (document.querySelector('input[name=code]')||{}).value||'';
    var files = Array.from(document.querySelectorAll('[fileurl]')).filter(function(el){
        return el.getAttribute('fileurl') && el.getAttribute('fileurl').includes('/upload/note/');
    }).map(function(el){
        return {fileurl: el.getAttribute('fileurl'), oriname: el.getAttribute('oriname')||''};
    });
    // 중복 제거
    var seen = {};
    files = files.filter(function(f){
        if(seen[f.fileurl]) return false;
        seen[f.fileurl] = true;
        return true;
    });
    JSON.stringify({code: code, files: files})
    """)
    try:
        return json.loads(r)
    except:
        return {}

def download_file(fileurl, oriname, note_code, cookie):
    """파일 다운로드"""
    try:
        fname = base64.b64decode(oriname).decode("utf-8")
    except:
        fname = oriname or "unknown"

    note_dir = SAVE_DIR / note_code
    note_dir.mkdir(parents=True, exist_ok=True)
    save_path = note_dir / fname

    if save_path.exists():
        return f"이미 존재: {fname}"

    url = f"{fileurl}/{oriname}"
    req = urllib.request.Request(url)
    req.add_header("Cookie", cookie)
    req.add_header("Referer", "http://stmsg.cbe.go.kr:7880/ezmaru/pc/noteDetail")
    req.add_header("User-Agent", "Mozilla/5.0")

    try:
        resp = urllib.request.urlopen(req, timeout=30)
        data = resp.read()
        save_path.write_bytes(data)

        # DB 저장
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS note_attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    note_code TEXT NOT NULL,
                    file_name TEXT,
                    file_size INTEGER,
                    local_path TEXT,
                    fileurl TEXT,
                    oriname TEXT,
                    download_ok INTEGER DEFAULT 1,
                    downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(note_code, oriname)
                )
            """)
            conn.execute("""
                INSERT OR IGNORE INTO note_attachments (note_code, file_name, file_size, local_path, fileurl, oriname)
                VALUES (?,?,?,?,?,?)
            """, (note_code, fname, len(data), str(save_path), fileurl, oriname))
            conn.commit()
        except Exception as e:
            pass
        finally:
            conn.close()

        return f"✓ {fname} ({len(data):,} bytes)"
    except urllib.error.HTTPError as e:
        return f"✗ HTTP {e.code}: {fname}"
    except Exception as e:
        return f"✗ 오류: {e} | {fname}"

# ── 메인 루프 ──────────────────────────────────────────
SAVE_DIR.mkdir(exist_ok=True)
print("=" * 60)
print("쪽지 첨부파일 수집기")
print("메신저에서 첨부파일 있는 쪽지를 클릭하세요!")
print("Ctrl+C 로 종료")
print("=" * 60)

# DB에서 파일 있는 쪽지 목록
conn = sqlite3.connect(DB_PATH)
notes_with_files = {r[0] for r in conn.execute("SELECT note_code FROM notes WHERE file_cnt > 0").fetchall()}
conn.close()
print(f"파일 있는 쪽지: {len(notes_with_files)}건")

seen_codes = set()  # 이미 처리한 note_code
cookie     = ""

try:
    while True:
        page = get_note_page()
        if not page:
            print("[대기] noteDetail 창이 없습니다. 쪽지를 열어주세요...", end="\r")
            time.sleep(2)
            continue

        try:
            ws = create_connection(page["webSocketDebuggerUrl"], timeout=10)
        except Exception:
            time.sleep(1)
            continue

        # 쿠키 갱신
        c = js(ws, 9000, "document.cookie")
        if c: cookie = c

        # DOM에서 현재 쪽지 + 파일 추출
        state = extract_files_from_dom(ws)
        ws.close()

        current_code = state.get("code", "")
        files = state.get("files", [])

        if current_code and current_code not in seen_codes and files:
            seen_codes.add(current_code)
            print(f"\n[감지] 쪽지 {current_code[:16]}... 파일 {len(files)}개")

            for f in files:
                result = download_file(f["fileurl"], f["oriname"], current_code, cookie)
                print(f"  {result}")

        remaining = notes_with_files - seen_codes
        done      = len(notes_with_files) - len(remaining)
        print(f"  진행: {done}/{len(notes_with_files)} 완료  ", end="\r")

        time.sleep(1.5)

except KeyboardInterrupt:
    conn = sqlite3.connect(DB_PATH)
    try:
        total = conn.execute("SELECT COUNT(*) FROM note_attachments").fetchone()[0]
    except:
        total = 0
    conn.close()
    print(f"\n\n종료. 총 다운로드: {total}개 파일")
    print(f"저장 위치: {SAVE_DIR}")
