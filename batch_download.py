# -*- coding: utf-8 -*-
"""
쪽지 첨부파일 배치 다운로더
- noteDetail_controller.noteDetail() + nteCode 파라미터 활용
- 221개 쪽지 자동 순회
"""
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

def load_note(ws, note_code):
    """hidden input 변경 후 noteDetail_controller.noteDetail() 호출"""
    return js(ws, 100, f"""
    try {{
        $('input[name=code]').val('{note_code}');
        $('input[name=sCode]').val('{note_code}');
        noteDetail_controller.noteDetail();
        'called'
    }} catch(e) {{ 'error:' + e.message }}
    """)

def get_files(ws, expected_code, timeout=8):
    """파일 로딩 완료 대기 후 추출"""
    start = time.time()
    while time.time() - start < timeout:
        r = js(ws, 200, """
        var code = $('input[name=code]').val() || '';
        var attBar = $('#noteDetail .attFileBar');
        var isHidden = attBar.hasClass('templateHidden');
        var files = Array.from(document.querySelectorAll('[fileurl]')).filter(function(el){
            return (el.getAttribute('fileurl')||'').includes('/upload/note/');
        }).map(function(el){
            return {fileurl: el.getAttribute('fileurl'), oriname: el.getAttribute('oriname')||''};
        });
        // 중복 제거
        var seen = {}, uniq = [];
        files.forEach(function(f){ if(!seen[f.fileurl]){ seen[f.fileurl]=1; uniq.push(f); }});
        JSON.stringify({code: code, files: uniq, attHidden: isHidden})
        """)
        try:
            state = json.loads(r)
            # 파일 바가 보이거나 (첨부있음) 또는 숨김 상태가 확정되면 완료
            if state.get('code') == expected_code:
                return state.get('files', [])
        except:
            pass
        time.sleep(0.4)
    return []

def download_file(fileurl, oriname, note_code, cookie):
    try:
        fname = base64.b64decode(oriname).decode("utf-8")
    except:
        fname = oriname

    note_dir = SAVE_DIR / note_code
    note_dir.mkdir(parents=True, exist_ok=True)
    save_path = note_dir / fname
    if save_path.exists():
        return f"[skip] {fname}"

    url = f"{fileurl}/{oriname}"
    req = urllib.request.Request(url)
    req.add_header("Cookie", cookie)
    req.add_header("Referer", "http://stmsg.cbe.go.kr:7880/ezmaru/pc/noteDetail")
    req.add_header("User-Agent", "Mozilla/5.0")
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        data = resp.read()
        save_path.write_bytes(data)
        # DB 기록
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute("""CREATE TABLE IF NOT EXISTS note_attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_code TEXT, file_name TEXT, file_size INTEGER,
                local_path TEXT, fileurl TEXT, oriname TEXT,
                download_ok INTEGER DEFAULT 1,
                downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(note_code, oriname))""")
            conn.execute("INSERT OR IGNORE INTO note_attachments VALUES (null,?,?,?,?,?,?,1,CURRENT_TIMESTAMP)",
                         (note_code, fname, len(data), str(save_path), fileurl, oriname))
            conn.commit()
        finally:
            conn.close()
        return f"✓ {fname} ({len(data):,} B)"
    except Exception as e:
        return f"✗ {fname} | {e}"

# ── 메인 ──────────────────────────────────────────────
conn = sqlite3.connect(DB_PATH)
notes = conn.execute("SELECT note_code, title, file_cnt FROM notes WHERE file_cnt > 0 ORDER BY note_date DESC").fetchall()

# 이미 다운로드된 목록
done_codes = set()
try:
    done_codes = {r[0] for r in conn.execute("SELECT DISTINCT note_code FROM note_attachments WHERE download_ok=1").fetchall()}
except:
    pass
conn.close()

pending = [n for n in notes if n[0] not in done_codes]
print(f"전체: {len(notes)}건 | 완료: {len(done_codes)}건 | 남은: {len(pending)}건")

ws_url = get_note_ws()
if not ws_url:
    print("ERROR: noteDetail 창이 없습니다. 메신저에서 쪽지를 하나 열어주세요.")
    exit(1)

ws = create_connection(ws_url, timeout=20)
cookie = js(ws, 1, "document.cookie")
print(f"쿠키: {cookie[:60]}...")
print()

# 배치 처리
BATCH_SIZE = 10  # 10개씩 처리 후 WS 재연결
success_total = 0
fail_total = 0

for i, (note_code, title, file_cnt) in enumerate(pending):
    print(f"[{i+1}/{len(pending)}] {title[:35]}... (파일{file_cnt}개)")

    # WS 재연결 (10개마다)
    if i > 0 and i % BATCH_SIZE == 0:
        try:
            ws.close()
        except:
            pass
        time.sleep(1)
        ws_url = get_note_ws()
        if not ws_url:
            print("  WS 연결 끊김, 재시도...")
            time.sleep(3)
            ws_url = get_note_ws()
        if ws_url:
            ws = create_connection(ws_url, timeout=20)
            cookie = js(ws, 1, "document.cookie")
        else:
            print("  noteDetail 창을 다시 열어주세요.")
            break

    # 쪽지 로드
    result = load_note(ws, note_code)
    if 'error' in str(result):
        print(f"  로드 실패: {result}")
        fail_total += 1
        continue

    # 파일 추출 대기
    files = get_files(ws, note_code, timeout=6)
    if not files:
        print(f"  파일 없음 (로딩 타임아웃 또는 파일 미감지)")
        fail_total += 1
        continue

    # 다운로드
    for f in files:
        res = download_file(f['fileurl'], f['oriname'], note_code, cookie)
        print(f"  {res}")
        if res.startswith("✓"):
            success_total += 1

    time.sleep(0.3)  # 서버 부하 방지

try:
    ws.close()
except:
    pass

print(f"\n완료: 성공 {success_total}건 | 실패/없음 {fail_total}건")
print(f"저장 위치: {SAVE_DIR}")
