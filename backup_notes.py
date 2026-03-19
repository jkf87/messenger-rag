"""
충북소통메신저 쪽지 전체 백업
- 받은쪽지 + 보낸쪽지 전체 수집
- python backup_notes.py
"""
import sys, json, time, sqlite3, urllib.request
from pathlib import Path
from websocket import create_connection

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CDP_URL = "http://127.0.0.1:9000/json"
DB_PATH = Path(__file__).parent / "messages.db"
PAGE_SIZE = 1000

# ── DB ───────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            note_code TEXT UNIQUE,
            note_type TEXT,
            sender    TEXT,
            receiver  TEXT,
            title     TEXT,
            content   TEXT,
            note_date TEXT,
            read_yn   TEXT,
            file_cnt  INTEGER DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_note_content ON notes(content)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_note_title  ON notes(title)")
    conn.commit()
    conn.close()

def save_notes(notes_list):
    conn = sqlite3.connect(DB_PATH)
    saved = 0
    for n in notes_list:
        try:
            conn.execute(
                """INSERT OR IGNORE INTO notes
                   (note_code,note_type,sender,receiver,title,content,note_date,read_yn,file_cnt)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (n["code"], n["type"], n["sender"], n["receiver"],
                 n["title"], n["content"], n["date"], n["read_yn"], n["file_cnt"])
            )
            saved += conn.execute("SELECT changes()").fetchone()[0]
        except Exception as e:
            pass
    conn.commit()
    conn.close()
    return saved

# ── CDP 유틸 ────────────────────────────────────────
def get_pages():
    try:
        with urllib.request.urlopen(CDP_URL, timeout=3) as r:
            return json.loads(r.read())
    except:
        return []

def ev_sync(ws, id_, expr):
    ws.send(json.dumps({"id": id_, "method": "Runtime.evaluate", "params": {"expression": expr}}))
    return json.loads(ws.recv()).get("result", {}).get("result", {}).get("value", "")

# ── 쪽지 목록 가져오기 ──────────────────────────────
def fetch_notes_page(ws, note_type, page_no):
    """note_type: 'receive' | 'send', 반환: 쪽지 dict 리스트"""
    raw = ev_sync(ws, page_no * 10, f"""
var r='';
$.ajax({{
    url: '/ezmaru/pc/note/noteList',
    type: 'POST',
    async: false,
    data: {{pageSize:{PAGE_SIZE}, pageNo:{page_no}, noteType:'{note_type}'}},
    success: function(d){{r=JSON.stringify(d.LIST);}},
    error: function(e){{r='ERR:'+e.status;}}
}});
r
""")
    if not raw or raw.startswith("ERR"):
        return []
    try:
        items = json.loads(raw)
    except:
        return []
    result = []
    for n in items:
        title   = (n.get("NTE_TITLE") or "").strip()
        content = (n.get("NTE_CONTENT") or n.get("CONTENTS") or "").strip()
        # HTML 태그 간단 제거
        import re
        content = re.sub(r'<[^>]+>', '', content).replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").strip()
        result.append({
            "code":     n.get("NTE_CODE", ""),
            "type":     note_type,
            "sender":   (n.get("NUR_NIC") or n.get("NUR_USERID") or "").strip(),
            "receiver": (n.get("RNIC") or "").strip(),
            "title":    title,
            "content":  content or title,
            "date":     n.get("NTE_REGDATE", ""),
            "read_yn":  n.get("READ_YN", ""),
            "file_cnt": int(n.get("FILE_CNT") or 0),
        })
    return result

def collect_notes(ws, note_type):
    label = "받은쪽지" if note_type == "receive" else "보낸쪽지"
    print(f"\n  [{label}] 수집 중...")
    total_saved = 0
    page_no = 1
    while True:
        items = fetch_notes_page(ws, note_type, page_no)
        if not items:
            break
        saved = save_notes(items)
        total_saved += saved
        print(f"    페이지 {page_no}: {len(items)}건 파싱 → {saved}건 신규 저장")
        if len(items) < PAGE_SIZE:
            break
        page_no += 1
        time.sleep(0.2)
    print(f"  [{label}] 완료: 총 {total_saved}건 신규")
    return total_saved

# ── 메인 ────────────────────────────────────────────
def main():
    print("=" * 55)
    print("충북소통메신저 쪽지 전체 백업")
    print("=" * 55)
    init_db()

    pages = get_pages()
    main_page = next((p for p in pages if "ezmaru/pc/main" in p.get("url", "")
                      and "webSocketDebuggerUrl" in p), None)
    if not main_page:
        print("[오류] 메신저 main 페이지를 찾을 수 없습니다.")
        print("  메신저를 실행하고 로그인해주세요.")
        return

    ws = create_connection(main_page["webSocketDebuggerUrl"], timeout=10)

    # 쪽지 탭 활성화
    ev_sync(ws, 1, 'try{document.querySelector("a.note").click();}catch(e){}')
    time.sleep(0.5)

    collect_notes(ws, "receive")
    collect_notes(ws, "send")

    ws.close()

    conn = sqlite3.connect(DB_PATH)
    total    = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    recv_cnt = conn.execute("SELECT COUNT(*) FROM notes WHERE note_type='receive'").fetchone()[0]
    send_cnt = conn.execute("SELECT COUNT(*) FROM notes WHERE note_type='send'").fetchone()[0]
    conn.close()

    print(f"\n{'='*55}")
    print(f"백업 완료: 총 {total}건 (받은쪽지 {recv_cnt} / 보낸쪽지 {send_cnt})")
    print(f"{'='*55}")

if __name__ == "__main__":
    main()
