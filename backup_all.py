"""
충북소통메신저 전체 백업
- 그룹 채팅방 + 1:1 메시지 전체 수집
- 실행 중 메신저가 열려 있어야 함
- python backup_all.py
"""
import sys, json, re, time, sqlite3, urllib.request
from pathlib import Path
from websocket import create_connection

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CDP_URL = "http://127.0.0.1:9000/json"
DB_PATH = Path(__file__).parent / "messages.db"

TIME_RE = re.compile(r'^\d{1,2}:\d{2}$')
DATE_RE = re.compile(r'^\d{4}년 \d{1,2}월 \d{1,2}일$')

# ── DB ───────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
    if cols and "content" not in cols:
        conn.execute("DROP TABLE messages")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            room_code TEXT, room_name TEXT, sender TEXT,
            content   TEXT, msg_time TEXT, msg_date TEXT,
            UNIQUE(room_code, sender, content, msg_time, msg_date)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_content ON messages(content)")
    conn.commit()
    conn.close()

def save_messages(room_code, room_name, msgs):
    conn = sqlite3.connect(DB_PATH)
    saved = 0
    for m in msgs:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO messages (room_code,room_name,sender,content,msg_time,msg_date) VALUES (?,?,?,?,?,?)",
                (room_code, room_name, m["sender"], m["content"], m["time"], m["date"])
            )
            saved += conn.execute("SELECT changes()").fetchone()[0]
        except: pass
    conn.commit()
    conn.close()
    return saved

# ── 파싱 ────────────────────────────────────────────
def clean(s):
    return s.replace("\xa0", " ").replace("\u200b", "").strip()

def parse_messages(inner_text):
    lines = [clean(l) for l in inner_text.split("\n") if clean(l)]
    skip  = ["방나가기", "※「정보통신망", "보내기", "파일첨부", "이모티콘", "확인"]
    lines = [l for l in lines if not any(l.startswith(s) for s in skip)]
    msgs, sender, date = [], "나", ""
    i = 0
    while i < len(lines):
        line = lines[i]
        if DATE_RE.match(line): date = line; i += 1; continue
        if TIME_RE.match(line):
            if msgs and msgs[-1]["time"] == "": msgs[-1]["time"] = line
            i += 1; continue
        next_l = lines[i+1] if i+1 < len(lines) else ""
        if TIME_RE.match(next_l):
            msgs.append({"sender":sender,"content":line,"time":next_l,"date":date})
            i += 2; continue
        prev_t = (i==0) or TIME_RE.match(lines[i-1]) or DATE_RE.match(lines[i-1])
        if prev_t and not TIME_RE.match(next_l) and len(line) < 25:
            sender = line; i += 1; continue
        msgs.append({"sender":sender,"content":line,"time":"","date":date})
        i += 1
    return msgs

# ── CDP 유틸 ────────────────────────────────────────
def get_pages():
    try:
        with urllib.request.urlopen(CDP_URL, timeout=3) as r:
            return json.loads(r.read())
    except: return []

def get_ws(url_keyword):
    for p in get_pages():
        if url_keyword in p.get("url","") and "webSocketDebuggerUrl" in p:
            return p["webSocketDebuggerUrl"], p["id"]
    return None, None

def ev_sync(ws, id_, expr):
    ws.send(json.dumps({"id":id_,"method":"Runtime.evaluate","params":{"expression":expr}}))
    return json.loads(ws.recv()).get("result",{}).get("result",{}).get("value","")

# ── 채팅창에서 메시지 읽기 ──────────────────────────
def read_detail_page(ws_url):
    """messageDetail 페이지에서 innerText + room 정보 반환"""
    try:
        ws = create_connection(ws_url, timeout=5)
        result = ev_sync(ws, 1, r"""
JSON.stringify({
    code: (document.getElementById("sCode")||{}).value||"",
    name: (function(){
        var t = document.querySelector(".chatTitle,.chat_title,[class*=roomTitle],[class*=chatName]");
        if(t&&t.textContent.trim()) return t.textContent.trim();
        var tn = (document.querySelector("[name=targetName]")||{}).value||"";
        var m = tn.match(/@@([^@]+)@@@/);
        if(m) return m[1].replace(/\[.*?\]/g,"").trim();
        return document.title||"";
    })(),
    text: document.body.innerText
})
""")
        ws.close()
        return json.loads(result)
    except Exception as e:
        if "being inspected" not in str(e):
            print(f"  [읽기오류] {e}")
        return None

def wait_for_detail_page(old_ids, timeout=8):
    """새 messageDetail 창이 열릴 때까지 대기"""
    start = time.time()
    while time.time() - start < timeout:
        for p in get_pages():
            if ("messageDetail" in p.get("url","") and
                "webSocketDebuggerUrl" in p and
                p["id"] not in old_ids):
                time.sleep(0.5)  # 페이지 로드 대기
                return p["webSocketDebuggerUrl"], p["id"]
        time.sleep(0.3)
    return None, None

def backup_from_detail(ws_url, label=""):
    """detail 창에서 메시지 읽어 DB 저장"""
    data = read_detail_page(ws_url)
    if not data or not data.get("code"):
        return 0
    code = data["code"]
    name = clean(data.get("name","")) or code
    msgs = parse_messages(data.get("text",""))
    saved = save_messages(code, name, msgs)
    status = f"{saved}건 신규" if saved else "새 메시지 없음"
    print(f"  [{label or name}] 파싱:{len(msgs)}건 → {status}")
    return saved

# ── 그룹 채팅방 전체 수집 ───────────────────────────
def collect_chatrooms(main_ws):
    print("\n[1단계] 그룹 채팅방 수집")
    raw = ev_sync(main_ws, 10, """
var r="{}";
$.ajax({url:"/ezmaru/pc/chatroom/chatroomlist",type:"POST",async:false,
    success:function(d){r=JSON.stringify(d);},error:function(e){r="ERR:"+e.status;}});
r
""")
    try:
        rooms = json.loads(raw).get("LIST",[])
    except:
        rooms = []
    print(f"  채팅방 {len(rooms)}개 발견")

    for room in rooms:
        code  = room.get("NCS_SCODE","")
        title = room.get("NCS_TITLE","")
        print(f"\n  → [{title}] 수집 중...")

        existing = {p["id"] for p in get_pages() if "webSocketDebuggerUrl" in p}

        # DOM에서 해당 채팅방 클릭
        clicked = ev_sync(main_ws, 11, f"""
var item = document.querySelector('[code="{code}"]');
if(item) {{ item.click(); "ok"; }} else {{ "not found"; }}
""")
        if clicked != "ok":
            # DOM에 없으면 chatroom_controller로 직접 열기
            ev_sync(main_ws, 12, f"""
try {{
    chatroomdetail_controller.chatRoomInfo("{code}");
}} catch(e) {{}}
""")

        ws_url, pid = wait_for_detail_page(existing, timeout=6)
        if ws_url:
            backup_from_detail(ws_url, title)
        else:
            print(f"  [{title}] 창 열기 실패 - 수동으로 열어주세요")

# ── 1:1 메시지 전체 수집 ────────────────────────────
def collect_messages(main_ws):
    print("\n[2단계] 1:1 메시지 수집")

    # 메시지 탭 클릭해서 세션 목록 로드
    ev_sync(main_ws, 20, """
var tab = document.querySelector("a.message, #message-tab, [data-mode=message], a[href*=message]");
if(tab) tab.click();
""")
    time.sleep(1)

    # sessionlist API 호출 (main 페이지에서 암호화)
    raw = ev_sync(main_ws, 21, """
var r="{}";
var encKey = EZMARU_ENCKEY_CHAT;
var enc = cryptoUtil.encryptAES256WithSHA256Key(JSON.stringify({pageSize:200, pageNo:1}), encKey);
$.ajax({
    url: "/ezmaru/pc/message/sessionlist",
    type: "POST",
    contentType: "application/json",
    async: false,
    data: JSON.stringify({head:{version:"1.0",enctype:"aes256sha256",compress:"",apikey:"",action:""},body:{data:enc}}),
    success: function(resp) {
        try {
            var dec = cryptoUtil.decryptAES256WithSHA256Key(resp.body.data, encKey);
            r = dec;
        } catch(e) { r = JSON.stringify(resp).substring(0,200); }
    },
    error: function(e){ r = "ERR:"+e.status; }
});
r
""")

    try:
        sessions_data = json.loads(raw)
        sessions = sessions_data.get("LIST", sessions_data.get("list", []))
    except:
        print(f"  세션 목록 파싱 실패: {str(raw)[:100]}")
        sessions = []

    print(f"  1:1 대화 {len(sessions)}개 발견")

    for sess in sessions:
        # 세션 코드 필드명 탐색
        code  = sess.get("NCS_SCODE", sess.get("SESSION_CODE", sess.get("code","")))
        title = sess.get("NCS_TITLE", sess.get("title", sess.get("NUR_NIC", code[:8])))
        if not code:
            continue

        print(f"\n  → [{title}] 수집 중...")
        existing = {p["id"] for p in get_pages() if "webSocketDebuggerUrl" in p}

        # DOM 클릭 또는 직접 열기
        clicked = ev_sync(main_ws, 22, f"""
var item = document.querySelector('[code="{code}"]');
if(item) {{ item.click(); "ok"; }} else {{ "not found"; }}
""")
        if clicked != "ok":
            # msgbox_controller로 직접 열기 시도
            ev_sync(main_ws, 23, f"""
try {{ msgbox_controller.detailItemView("{code}"); }} catch(e) {{}}
""")

        ws_url, pid = wait_for_detail_page(existing, timeout=8)
        if ws_url:
            backup_from_detail(ws_url, title)
        else:
            print(f"  [{title}] 창 열기 실패")

# ── 현재 열린 창 수집 ───────────────────────────────
def collect_open_windows():
    print("\n[0단계] 현재 열린 채팅창 수집")
    pages = get_pages()
    detail_pages = [p for p in pages
                    if "messageDetail" in p.get("url","") and "webSocketDebuggerUrl" in p]
    print(f"  열린 창 {len(detail_pages)}개")
    total = 0
    for p in detail_pages:
        total += backup_from_detail(p["webSocketDebuggerUrl"])
    return total

# ── 메인 ────────────────────────────────────────────
def main():
    print("=" * 55)
    print("충북소통메신저 전체 백업")
    print("=" * 55)
    init_db()

    # main 페이지 CDP 연결
    main_ws_url, _ = get_ws("ezmaru/pc/main")
    if not main_ws_url:
        print("[오류] 메신저 main 페이지를 찾을 수 없습니다.")
        print("  메신저를 실행하고 로그인해주세요.")
        return

    main_ws = create_connection(main_ws_url, timeout=10)

    # 0. 현재 열린 창 먼저
    collect_open_windows()

    # 1. 그룹 채팅방
    collect_chatrooms(main_ws)

    # 2. 1:1 메시지
    collect_messages(main_ws)

    main_ws.close()

    total = sqlite3.connect(DB_PATH).execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    rooms_cnt = sqlite3.connect(DB_PATH).execute("SELECT COUNT(DISTINCT room_code) FROM messages").fetchone()[0]
    print(f"\n{'='*55}")
    print(f"백업 완료: 총 {total}건 / {rooms_cnt}개 대화방")
    print(f"{'='*55}")

if __name__ == "__main__":
    main()
