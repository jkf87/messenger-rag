"""
충북소통메신저 백업 도구
- 열린 채팅창(messageDetail)을 자동 감지하고 메시지 추출
- 실행 후 채팅창을 여닫으면 자동으로 백업됨
- python backup.py
"""
import sys, json, re, time, sqlite3, threading, urllib.request
from pathlib import Path
from websocket import create_connection, WebSocketConnectionClosedException

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CDP_URL  = "http://127.0.0.1:9000/json"
DB_PATH  = Path(__file__).parent / "messages.db"
POLL_SEC = 3   # 새 채팅창 확인 주기

# ── DB ───────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    # 기존 테이블 스키마 확인 후 필요시 재생성
    cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
    if cols and "content" not in cols:
        print("[DB] 스키마 변경 - 테이블 재생성")
        conn.execute("DROP TABLE messages")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_code TEXT,
            room_name TEXT,
            sender    TEXT,
            content   TEXT,
            msg_time  TEXT,
            msg_date  TEXT,
            saved_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(room_code, sender, content, msg_time, msg_date)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_content ON messages(content)")
    conn.commit()
    conn.close()

def save_messages(room_code, room_name, msgs):
    if not msgs:
        return 0
    conn = sqlite3.connect(DB_PATH)
    saved = 0
    for m in msgs:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO messages (room_code,room_name,sender,content,msg_time,msg_date) VALUES (?,?,?,?,?,?)",
                (room_code, room_name, m["sender"], m["content"], m["time"], m["date"])
            )
            saved += conn.execute("SELECT changes()").fetchone()[0]
        except Exception as e:
            pass
    conn.commit()
    conn.close()
    return saved

# ── 메시지 파싱 ───────────────────────────────────────
TIME_RE = re.compile(r'^\d{1,2}:\d{2}$')
DATE_RE = re.compile(r'^\d{4}년 \d{1,2}월 \d{1,2}일$')

def clean(s):
    return s.replace("\xa0", " ").replace("\u200b", "").strip()

def parse_messages(inner_text, my_name="나"):
    """innerText를 파싱해서 메시지 리스트 반환"""
    lines = [clean(l) for l in inner_text.split("\n") if clean(l)]

    # 불필요한 헤더 제거
    skip_prefixes = ["방나가기", "※「정보통신망", "보내기", "파일첨부", "이모티콘"]
    lines = [l for l in lines if not any(l.startswith(p) for p in skip_prefixes)]

    messages = []
    current_sender = my_name
    current_date   = ""
    i = 0

    while i < len(lines):
        line = lines[i]

        # 날짜 구분선
        if DATE_RE.match(line):
            current_date = line
            i += 1
            continue

        # 시간 패턴 → 바로 앞 라인이 메시지
        if TIME_RE.match(line):
            if messages and messages[-1]["time"] == "":
                messages[-1]["time"] = line
            i += 1
            continue

        # 다음 줄이 시간이면 현재 줄은 메시지 (발신자 없는 경우 = 내 메시지)
        next_line = lines[i+1] if i+1 < len(lines) else ""
        after_next = lines[i+2] if i+2 < len(lines) else ""

        if TIME_RE.match(next_line):
            # 발신자를 구분 - 이름이 별도 라인으로 있고 그 다음이 메시지+시간 패턴
            messages.append({
                "sender":  current_sender,
                "content": line,
                "time":    next_line,
                "date":    current_date
            })
            i += 2
            continue

        # 발신자 이름 블록 (이름 다음에 메시지, 시간 순서)
        # 이름 라인 다음이 시간이 아니고, 그 다음 다음이 시간이면 이름 가능성
        if not TIME_RE.match(line) and not DATE_RE.match(line):
            # 연속된 메시지 그룹에서 발신자 이름인지 확인
            # 발신자 이름은 단독 라인 (짧고, 그 앞이 시간 라인이거나 첫 줄)
            prev_was_time = (i == 0) or TIME_RE.match(lines[i-1]) or DATE_RE.match(lines[i-1])
            if prev_was_time and not TIME_RE.match(next_line):
                # 이름으로 간주
                current_sender = line
                i += 1
                continue

        messages.append({
            "sender":  current_sender,
            "content": line,
            "time":    "",
            "date":    current_date
        })
        i += 1

    return [m for m in messages if m["content"] and len(m["content"]) > 0]

# ── CDP 채팅창 모니터링 ───────────────────────────────
monitored = {}   # page_id -> {"ws": ws, "room_code": code, "room_name": name}

def get_pages():
    try:
        with urllib.request.urlopen(CDP_URL, timeout=3) as r:
            return json.loads(r.read())
    except:
        return []

def extract_room_info(ws_conn):
    """채팅창에서 room_code, room_name 추출"""
    try:
        ws_conn.send(json.dumps({"id":1,"method":"Runtime.evaluate","params":{
            "expression": r"""
JSON.stringify({
    code: (document.getElementById("sCode")||{}).value || "",
    name: (function(){
        var t = document.querySelector(".chatTitle,.chat_title,[class*=roomTitle],[class*=chatName]");
        if(t && t.textContent.trim()) return t.textContent.trim();
        var target = (document.querySelector("[name=targetName]")||{}).value || "";
        var m = target.match(/@@([^@]+)@@@/);
        if(m) return m[1].replace(/\[.*?\]/g,"").trim();
        return document.title || "";
    })()
})
"""
        }}))
        r = json.loads(ws_conn.recv())
        val = r.get("result",{}).get("result",{}).get("value","{}")
        return json.loads(val)
    except:
        return {"code":"","name":""}

def backup_page(page_id, ws_url):
    """채팅창 innerText 읽고 파싱 후 DB 저장"""
    try:
        ws = create_connection(ws_url, timeout=5)
        info = extract_room_info(ws)
        if not info.get("code"):
            ws.close()
            return
        room_code = info.get("code","unknown")
        room_name = info.get("name","") or room_code

        # innerText 전체 읽기
        ws.send(json.dumps({"id":2,"method":"Runtime.evaluate","params":{
            "expression":"document.body.innerText"
        }}))
        r = json.loads(ws.recv())
        text = r.get("result",{}).get("result",{}).get("value","")
        ws.close()

        if not text:
            return

        msgs = parse_messages(text)
        saved = save_messages(room_code, room_name, msgs)
        if saved > 0:
            print(f"[백업] {room_name} ({room_code}) → {saved}건 저장 (파싱:{len(msgs)}건)")
        else:
            print(f"[백업] {room_name} → 새 메시지 없음 (파싱:{len(msgs)}건)")

    except Exception as e:
        if "being inspected" not in str(e):  # 다른 CDP 연결 충돌은 무시
            print(f"[백업 오류] {page_id[:8]}: {e}")

def monitor_loop():
    """주기적으로 열린 채팅창 감지 및 백업"""
    known_pages   = set()   # 이미 처음 백업 완료한 페이지
    refresh_times = {}      # 마지막 갱신 시간
    REFRESH_SEC   = 30      # 기존 창 재백업 주기
    print(f"[모니터] 채팅창 감지 시작 (신규 즉시 / 기존 {REFRESH_SEC}초마다)")
    while True:
        pages = get_pages()
        current = {
            p["id"]: p["webSocketDebuggerUrl"]
            for p in pages
            if "messageDetail" in p.get("url","") and "webSocketDebuggerUrl" in p
        }

        now = time.time()
        for pid, ws_url in current.items():
            if pid not in known_pages:
                print(f"[감지] 새 채팅창: {pid[:8]}...")
                threading.Thread(target=backup_page, args=(pid, ws_url), daemon=True).start()
                known_pages.add(pid)
                refresh_times[pid] = now
            elif now - refresh_times.get(pid, 0) >= REFRESH_SEC:
                threading.Thread(target=backup_page, args=(pid, ws_url), daemon=True).start()
                refresh_times[pid] = now

        # 닫힌 창 제거
        closed = known_pages - set(current.keys())
        known_pages  -= closed
        for pid in closed:
            refresh_times.pop(pid, None)

        time.sleep(POLL_SEC)

# ── 메인 ────────────────────────────────────────────
def main():
    print("=" * 50)
    print("충북소통메신저 백업 도구")
    print("=" * 50)
    init_db()

    # 현재 열린 채팅창 즉시 백업
    pages = get_pages()
    detail_pages = [p for p in pages if "messageDetail" in p.get("url","") and "webSocketDebuggerUrl" in p]
    if detail_pages:
        print(f"[초기] 열린 채팅창 {len(detail_pages)}개 즉시 백업")
        for p in detail_pages:
            backup_page(p["id"], p["webSocketDebuggerUrl"])
    else:
        print("[대기] 채팅창을 열면 자동으로 백업됩니다")

    total = sqlite3.connect(DB_PATH).execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    print(f"[DB] 현재 저장된 메시지: {total}건")
    print("\n채팅창을 열어두면 자동 백업됩니다. Ctrl+C로 종료\n")

    try:
        monitor_loop()
    except KeyboardInterrupt:
        total = sqlite3.connect(DB_PATH).execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        print(f"\n[종료] 총 {total}건 저장됨")

if __name__ == "__main__":
    main()
