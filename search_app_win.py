"""
메시지/쪽지 RAG 검색 - Windows 앱
실행: python search_app_win.py
"""
import sys, sqlite3, os, threading, re, subprocess, json
from pathlib import Path
import tkinter as tk
from tkinter import ttk

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_PATH     = Path(__file__).parent / "messages.db"
CONFIG_PATH = Path(__file__).parent / "config.json"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

def _load_config():
    """config.json에서 API 키 등 설정 로드."""
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            for k in ("GLM_API_KEY", "ANTHROPIC_API_KEY"):
                if cfg.get(k) and not os.environ.get(k):
                    os.environ[k] = cfg[k]
        except Exception:
            pass

def _save_config(key: str, value: str):
    """config.json에 설정 저장."""
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    cfg[key] = value
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

_load_config()

# 로컬 RAG 가용 여부
try:
    from local_rag import is_index_ready, rag_search_notes, rag_search_messages, _load
    LOCAL_RAG_AVAILABLE = is_index_ready()
except ImportError:
    LOCAL_RAG_AVAILABLE = False
    def is_index_ready(): return False

# 앱 시작 시 백그라운드에서 RAG 모델 미리 로드
_rag_ready = False
_rag_loading = False

def _preload_rag():
    global _rag_ready, _rag_loading
    if not LOCAL_RAG_AVAILABLE:
        return
    _rag_loading = True
    try:
        _load()
        _rag_ready = True
    except Exception:
        pass
    _rag_loading = False

if LOCAL_RAG_AVAILABLE:
    threading.Thread(target=_preload_rag, daemon=True).start()

# ── 날짜 포맷 ─────────────────────────────────────────
def fmt_note_date(d):
    """20260319151418891 → 2026-03-19 15:14"""
    if not d or len(d) < 12:
        return d or ""
    try:
        return f"{d[0:4]}-{d[4:6]}-{d[6:8]} {d[8:10]}:{d[10:12]}"
    except:
        return d

# ── DB 통계 ───────────────────────────────────────────
def get_stats():
    if not DB_PATH.exists():
        return 0, 0, 0, []
    conn = sqlite3.connect(DB_PATH)
    msg_total  = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    note_total = 0
    try:
        note_total = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    except:
        pass
    rooms = conn.execute("SELECT COUNT(DISTINCT room_code) FROM messages").fetchone()[0]
    room_list = conn.execute(
        "SELECT room_code, COALESCE(NULLIF(room_name,''), room_code) FROM messages GROUP BY room_code ORDER BY room_name"
    ).fetchall()
    conn.close()
    return msg_total, note_total, rooms, room_list

# ── 검색 로직 ─────────────────────────────────────────
def _parse_date(d):
    """'2026-03-19' → '20260319', 빈 문자열이면 None"""
    if not d:
        return None
    return d.replace("-", "").replace("/", "").replace(".", "")[:8]

def search_messages(q, room="", sender="", date_from="", date_to=""):
    conn = sqlite3.connect(DB_PATH)
    sql    = "SELECT room_code,room_name,sender,content,msg_time,msg_date FROM messages WHERE content LIKE ?"
    params = [f"%{q}%"]
    if room:   sql += " AND room_code=?";    params.append(room)
    if sender: sql += " AND sender LIKE ?";  params.append(f"%{sender}%")
    df = _parse_date(date_from)
    dt = _parse_date(date_to)
    if df: sql += " AND msg_date >= ?"; params.append(df)
    if dt: sql += " AND msg_date <= ?"; params.append(dt)
    sql += " ORDER BY msg_date DESC, msg_time DESC LIMIT 200"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows

def search_notes(q, note_type="all", sender="", date_from="", date_to=""):
    conn = sqlite3.connect(DB_PATH)
    try:
        sql    = "SELECT note_code,note_type,sender,receiver,title,content,note_date,read_yn,file_cnt FROM notes WHERE (title LIKE ? OR content LIKE ?)"
        params = [f"%{q}%", f"%{q}%"]
        if note_type == "receive": sql += " AND note_type='receive'"
        elif note_type == "send":  sql += " AND note_type='send'"
        if sender: sql += " AND sender LIKE ?"; params.append(f"%{sender}%")
        df = _parse_date(date_from)
        dt = _parse_date(date_to)
        if df: sql += " AND note_date >= ?"; params.append(df)
        if dt: sql += " AND note_date <= ?"; params.append(dt + "9")  # 당일 포함
        sql += " ORDER BY note_date DESC LIMIT 200"
        rows = conn.execute(sql, params).fetchall()
    except:
        rows = []
    conn.close()
    return rows

def semantic_search_messages(q, room="", sender="", date_from="", date_to=""):
    import anthropic
    conn = sqlite3.connect(DB_PATH)
    sql    = "SELECT room_code,room_name,sender,content,msg_time,msg_date FROM messages WHERE content LIKE ?"
    params = [f"%{q}%"]
    if room:   sql += " AND room_code=?"; params.append(room)
    if sender: sql += " AND sender LIKE ?"; params.append(f"%{sender}%")
    df = _parse_date(date_from)
    dt = _parse_date(date_to)
    if df: sql += " AND msg_date >= ?"; params.append(df)
    if dt: sql += " AND msg_date <= ?"; params.append(dt)
    sql += " ORDER BY msg_date DESC LIMIT 100"
    rows = conn.execute(sql, params).fetchall()
    if len(rows) < 10:
        extra = conn.execute(
            "SELECT room_code,room_name,sender,content,msg_time,msg_date FROM messages ORDER BY msg_date DESC LIMIT 200"
        ).fetchall()
        seen  = {(r[0], r[3]) for r in rows}
        rows += [r for r in extra if (r[0], r[3]) not in seen][:100]
    conn.close()
    if not rows:
        return [], "AI-없음"
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    cands  = "\n".join(f"[{i}] {r[1]}|{r[2]}|{r[3][:80]}|{r[4]}" for i, r in enumerate(rows[:80]))
    prompt = f'다음 메시지 목록에서 "{q}"와 관련된 것을 관련성 순으로 최대 20개 번호만 반환 (쉼표 구분):\n{cands}'
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        idxs = [int(x.strip()) for x in resp.content[0].text.split(",") if x.strip().isdigit()]
        return [rows[i] for i in idxs if i < len(rows)], "AI 의미검색"
    except:
        return rows, "키워드(AI오류)"

def semantic_search_notes(q, note_type="all", sender="", date_from="", date_to=""):
    import anthropic
    rows = search_notes(q, note_type, sender, date_from, date_to)
    if len(rows) < 5:
        conn = sqlite3.connect(DB_PATH)
        try:
            extra = conn.execute(
                "SELECT note_code,note_type,sender,receiver,title,content,note_date,read_yn,file_cnt FROM notes ORDER BY note_date DESC LIMIT 100"
            ).fetchall()
            seen  = {r[0] for r in rows}
            rows += [r for r in extra if r[0] not in seen][:50]
        except: pass
        conn.close()
    if not rows:
        return [], "AI-없음"
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    cands  = "\n".join(f"[{i}] {r[2]}|{r[4][:60]}|{r[5][:60]}" for i, r in enumerate(rows[:60]))
    prompt = f'다음 쪽지 목록에서 "{q}"와 관련된 것을 관련성 순으로 최대 20개 번호만 반환 (쉼표 구분):\n{cands}'
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        idxs = [int(x.strip()) for x in resp.content[0].text.split(",") if x.strip().isdigit()]
        return [rows[i] for i in idxs if i < len(rows)], "AI 의미검색"
    except:
        return rows, "키워드(AI오류)"

# ── GUI ──────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("충북소통메신저 검색")
        self.geometry("1000x700")
        self.minsize(750, 520)
        self.configure(bg="#f0f2f5")
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except:
            pass
        self._search_mode = "msg"  # "msg" | "note"
        self._use_rag = tk.BooleanVar(value=LOCAL_RAG_AVAILABLE)
        self._last_note_rows = []
        self._last_note_query = ""
        self._build_ui()
        self._load_rooms()
        self._update_stats()

    # ── UI 구성 ───────────────────────────────────────
    def _build_ui(self):
        # 헤더
        hdr = tk.Frame(self, bg="#4a90d9", height=50)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="충북소통메신저 검색", bg="#4a90d9", fg="white",
                 font=("맑은 고딕", 13, "bold")).pack(side="left", padx=16, pady=10)
        self.lbl_stats = tk.Label(hdr, text="", bg="#4a90d9", fg="#d0e8ff",
                                   font=("맑은 고딕", 9))
        self.lbl_stats.pack(side="right", padx=16)

        # API 키 입력 (헤더 오른쪽)
        self._api_key_var = tk.StringVar(value=os.environ.get("GLM_API_KEY", os.environ.get("ANTHROPIC_API_KEY", "")))
        tk.Label(hdr, text="API Key:", bg="#4a90d9", fg="#d0e8ff",
                 font=("맑은 고딕", 9)).pack(side="right", padx=(0, 2))
        self._entry_apikey = tk.Entry(hdr, textvariable=self._api_key_var,
                                       width=32, font=("맑은 고딕", 9),
                                       relief="flat", show="*", bg="#3a7bc8", fg="white",
                                       insertbackground="white")
        self._entry_apikey.pack(side="right", ipady=4, pady=10)
        self._entry_apikey.bind("<FocusIn>",  lambda e: self._entry_apikey.config(show=""))
        self._entry_apikey.bind("<FocusOut>", lambda e: self._entry_apikey.config(show="*"))
        tk.Button(hdr, text="저장", command=self._save_api_key,
                  bg="#2d6baa", fg="white", font=("맑은 고딕", 8),
                  relief="flat", padx=8, cursor="hand2").pack(side="right", padx=(0, 4), pady=10)

        # 모드 탭 (메시지 / 쪽지)
        tab_frame = tk.Frame(self, bg="#e8edf2", height=36)
        tab_frame.pack(fill="x")
        tab_frame.pack_propagate(False)

        self.btn_msg  = tk.Button(tab_frame, text="💬 채팅 메시지",
                                   command=lambda: self._switch_mode("msg"),
                                   font=("맑은 고딕", 10), relief="flat",
                                   bg="#4a90d9", fg="white", padx=20, pady=6, cursor="hand2")
        self.btn_msg.pack(side="left")

        self.btn_note = tk.Button(tab_frame, text="📨 쪽지",
                                   command=lambda: self._switch_mode("note"),
                                   font=("맑은 고딕", 10), relief="flat",
                                   bg="#e8edf2", fg="#333", padx=20, pady=6, cursor="hand2")
        self.btn_note.pack(side="left")

        self.btn_wiki = tk.Button(tab_frame, text="📖 Wiki 답변",
                                   command=lambda: self._switch_mode("wiki"),
                                   font=("맑은 고딕", 10), relief="flat",
                                   bg="#e8edf2", fg="#333", padx=20, pady=6, cursor="hand2")
        self.btn_wiki.pack(side="left")

        # 수집 버튼 (탭 바 오른쪽)
        collect_btns = [
            ("📥 쪽지수집",   self._run_backup_notes),
            ("📄 본문수집",   self._run_fetch_content),
            ("📎 첨부수집",   self._run_batch_download),
            ("🔄 인덱스",     self._run_build_index),
            ("📖 Wiki빌드",   self._run_wiki_ingest),
        ]
        self._collect_buttons = []
        for label, cmd in reversed(collect_btns):
            b = tk.Button(tab_frame, text=label, command=cmd,
                          font=("맑은 고딕", 9), relief="flat",
                          bg="#e8edf2", fg="#555", padx=10, pady=6, cursor="hand2")
            b.pack(side="right", padx=1)
            self._collect_buttons.append(b)

        # 수집 진행 상태 표시줄 (탭바 바로 아래 고정)
        self._collect_status = tk.Label(self, text="", bg="#fff8e1",
                                         font=("맑은 고딕", 9), fg="#7a5800",
                                         anchor="w", relief="flat")
        self._collect_status.pack(fill="x", padx=0, pady=0)

        # 검색 영역
        self.search_frame = tk.Frame(self, bg="white", pady=10)
        self.search_frame.pack(fill="x", padx=12, pady=(10, 0))

        row1 = tk.Frame(self.search_frame, bg="white")
        row1.pack(fill="x", padx=12)

        self.entry_q = tk.Entry(row1, font=("맑은 고딕", 11), relief="solid", bd=1)
        self.entry_q.pack(side="left", fill="x", expand=True, ipady=6)
        self.entry_q.bind("<Return>", lambda e: self._search())

        btn = tk.Button(row1, text="검색", command=self._search,
                        bg="#4a90d9", fg="white", font=("맑은 고딕", 10, "bold"),
                        relief="flat", padx=16, pady=6, cursor="hand2")
        btn.pack(side="left", padx=(8, 0))

        # 로컬 RAG 토글
        rag_state = "normal" if LOCAL_RAG_AVAILABLE else "disabled"
        rag_text  = "로컬 RAG" if LOCAL_RAG_AVAILABLE else "로컬 RAG (인덱스 없음)"
        self._chk_rag = tk.Checkbutton(
            row1, text=rag_text, variable=self._use_rag,
            font=("맑은 고딕", 9), bg="white", fg="#4a90d9",
            activebackground="white", cursor="hand2", state=rag_state,
            command=self._update_stats
        )
        self._chk_rag.pack(side="left", padx=(12, 0))

        # 필터 행 (메시지용)
        self.row_msg_filter = tk.Frame(self.search_frame, bg="white")
        self.row_msg_filter.pack(fill="x", padx=12, pady=(8, 4))

        tk.Label(self.row_msg_filter, text="채팅방:", bg="white", font=("맑은 고딕", 9)).pack(side="left")
        self.cmb_room = ttk.Combobox(self.row_msg_filter, width=20, font=("맑은 고딕", 9), state="readonly")
        self.cmb_room.pack(side="left", padx=(4, 16))

        tk.Label(self.row_msg_filter, text="발신자:", bg="white", font=("맑은 고딕", 9)).pack(side="left")
        self.entry_sender_msg = tk.Entry(self.row_msg_filter, width=14, font=("맑은 고딕", 9), relief="solid", bd=1)
        self.entry_sender_msg.pack(side="left", padx=(4, 16), ipady=3)

        tk.Label(self.row_msg_filter, text="날짜:", bg="white", font=("맑은 고딕", 9)).pack(side="left")
        self.entry_date_from_msg = tk.Entry(self.row_msg_filter, width=11, font=("맑은 고딕", 9), relief="solid", bd=1, fg="#888")
        self.entry_date_from_msg.insert(0, "YYYY-MM-DD")
        self.entry_date_from_msg.pack(side="left", padx=(4, 2), ipady=3)
        self.entry_date_from_msg.bind("<FocusIn>",  lambda e: self._clear_placeholder(self.entry_date_from_msg, "YYYY-MM-DD"))
        self.entry_date_from_msg.bind("<FocusOut>", lambda e: self._restore_placeholder(self.entry_date_from_msg, "YYYY-MM-DD"))
        tk.Label(self.row_msg_filter, text="~", bg="white", font=("맑은 고딕", 9)).pack(side="left")
        self.entry_date_to_msg = tk.Entry(self.row_msg_filter, width=11, font=("맑은 고딕", 9), relief="solid", bd=1, fg="#888")
        self.entry_date_to_msg.insert(0, "YYYY-MM-DD")
        self.entry_date_to_msg.pack(side="left", padx=(2, 0), ipady=3)
        self.entry_date_to_msg.bind("<FocusIn>",  lambda e: self._clear_placeholder(self.entry_date_to_msg, "YYYY-MM-DD"))
        self.entry_date_to_msg.bind("<FocusOut>", lambda e: self._restore_placeholder(self.entry_date_to_msg, "YYYY-MM-DD"))

        self.lbl_mode = tk.Label(self.row_msg_filter, text="", bg="white", font=("맑은 고딕", 9), fg="#888")
        self.lbl_mode.pack(side="right")

        # 필터 행 (쪽지용)
        self.row_note_filter = tk.Frame(self.search_frame, bg="white")

        tk.Label(self.row_note_filter, text="종류:", bg="white", font=("맑은 고딕", 9)).pack(side="left")
        self.cmb_note_type = ttk.Combobox(self.row_note_filter, width=10, font=("맑은 고딕", 9), state="readonly",
                                           values=["전체", "받은쪽지", "보낸쪽지"])
        self.cmb_note_type.set("전체")
        self.cmb_note_type.pack(side="left", padx=(4, 16))

        tk.Label(self.row_note_filter, text="발신자:", bg="white", font=("맑은 고딕", 9)).pack(side="left")
        self.entry_sender_note = tk.Entry(self.row_note_filter, width=14, font=("맑은 고딕", 9), relief="solid", bd=1)
        self.entry_sender_note.pack(side="left", padx=(4, 16), ipady=3)

        tk.Label(self.row_note_filter, text="날짜:", bg="white", font=("맑은 고딕", 9)).pack(side="left")
        self.entry_date_from_note = tk.Entry(self.row_note_filter, width=11, font=("맑은 고딕", 9), relief="solid", bd=1, fg="#888")
        self.entry_date_from_note.insert(0, "YYYY-MM-DD")
        self.entry_date_from_note.pack(side="left", padx=(4, 2), ipady=3)
        self.entry_date_from_note.bind("<FocusIn>",  lambda e: self._clear_placeholder(self.entry_date_from_note, "YYYY-MM-DD"))
        self.entry_date_from_note.bind("<FocusOut>", lambda e: self._restore_placeholder(self.entry_date_from_note, "YYYY-MM-DD"))
        tk.Label(self.row_note_filter, text="~", bg="white", font=("맑은 고딕", 9)).pack(side="left")
        self.entry_date_to_note = tk.Entry(self.row_note_filter, width=11, font=("맑은 고딕", 9), relief="solid", bd=1, fg="#888")
        self.entry_date_to_note.insert(0, "YYYY-MM-DD")
        self.entry_date_to_note.pack(side="left", padx=(2, 0), ipady=3)
        self.entry_date_to_note.bind("<FocusIn>",  lambda e: self._clear_placeholder(self.entry_date_to_note, "YYYY-MM-DD"))
        self.entry_date_to_note.bind("<FocusOut>", lambda e: self._restore_placeholder(self.entry_date_to_note, "YYYY-MM-DD"))

        self.lbl_mode_note = tk.Label(self.row_note_filter, text="", bg="white", font=("맑은 고딕", 9), fg="#888")
        self.lbl_mode_note.pack(side="right")

        # 결과 상태
        self.lbl_result_info = tk.Label(self, text="", bg="#f0f2f5",
                                         font=("맑은 고딕", 9), fg="#666", anchor="w")
        self.lbl_result_info.pack(fill="x", padx=14, pady=(6, 2))

        # ── 좌우 분할: 좌=검색결과, 우=Graph RAG 추론 ───
        self._outer_paned = tk.PanedWindow(self, orient="horizontal", sashwidth=6,
                                            sashrelief="flat", bg="#c8d0d8",
                                            opaqueresize=True)
        self._outer_paned.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        # ── 상하 분할 패널 (트리 + 상세 크기 조절) ────────
        self._paned = tk.PanedWindow(self._outer_paned, orient="vertical", sashwidth=6,
                                      sashrelief="flat", bg="#c8d0d8",
                                      opaqueresize=True)
        self._outer_paned.add(self._paned, stretch="always", minsize=420)

        # 트리 컨테이너 (상단 패널)
        tree_outer = tk.Frame(self._paned, bg="#f0f2f5")
        self._paned.add(tree_outer, stretch="always", minsize=120)

        # TreeView (메시지용)
        self.tree_frame_msg = tk.Frame(tree_outer, bg="#f0f2f5")
        self.tree_frame_msg.pack(fill="both", expand=True)

        cols_msg = ("sender", "room", "content", "time", "date")
        self.tree_msg = ttk.Treeview(self.tree_frame_msg, columns=cols_msg, show="headings", selectmode="browse")
        self.tree_msg.heading("sender",  text="발신자")
        self.tree_msg.heading("room",    text="채팅방")
        self.tree_msg.heading("content", text="내용")
        self.tree_msg.heading("time",    text="시간")
        self.tree_msg.heading("date",    text="날짜")
        self.tree_msg.column("sender",  width=100, minwidth=60,  stretch=False)
        self.tree_msg.column("room",    width=140, minwidth=80,  stretch=False)
        self.tree_msg.column("content", width=520, minwidth=200, stretch=True)
        self.tree_msg.column("time",    width=55,  minwidth=45,  stretch=False)
        self.tree_msg.column("date",    width=100, minwidth=80,  stretch=False)

        vsb1 = ttk.Scrollbar(self.tree_frame_msg, orient="vertical",   command=self.tree_msg.yview)
        hsb1 = ttk.Scrollbar(self.tree_frame_msg, orient="horizontal", command=self.tree_msg.xview)
        self.tree_msg.configure(yscrollcommand=vsb1.set, xscrollcommand=hsb1.set)
        self.tree_msg.grid(row=0, column=0, sticky="nsew")
        vsb1.grid(row=0, column=1, sticky="ns")
        hsb1.grid(row=1, column=0, sticky="ew")
        self.tree_frame_msg.grid_rowconfigure(0, weight=1)
        self.tree_frame_msg.grid_columnconfigure(0, weight=1)
        self.tree_msg.bind("<<TreeviewSelect>>", self._on_select_msg)
        self.tree_msg.insert("", "end", values=("", "", "검색어를 입력하고 Enter 또는 검색 버튼을 클릭하세요", "", ""))

        # TreeView (쪽지용)
        self.tree_frame_note = tk.Frame(tree_outer, bg="#f0f2f5")

        cols_note = ("type", "sender", "receiver", "title", "date", "files")
        self.tree_note = ttk.Treeview(self.tree_frame_note, columns=cols_note, show="headings", selectmode="browse")
        self.tree_note.heading("type",     text="종류")
        self.tree_note.heading("sender",   text="보낸이")
        self.tree_note.heading("receiver", text="받는이")
        self.tree_note.heading("title",    text="제목/내용")
        self.tree_note.heading("date",     text="날짜")
        self.tree_note.heading("files",    text="첨부")
        self.tree_note.column("type",     width=70,  minwidth=50,  stretch=False)
        self.tree_note.column("sender",   width=110, minwidth=60,  stretch=False)
        self.tree_note.column("receiver", width=110, minwidth=60,  stretch=False)
        self.tree_note.column("title",    width=520, minwidth=200, stretch=True)
        self.tree_note.column("date",     width=120, minwidth=90,  stretch=False)
        self.tree_note.column("files",    width=40,  minwidth=30,  stretch=False)

        vsb2 = ttk.Scrollbar(self.tree_frame_note, orient="vertical",   command=self.tree_note.yview)
        hsb2 = ttk.Scrollbar(self.tree_frame_note, orient="horizontal", command=self.tree_note.xview)
        self.tree_note.configure(yscrollcommand=vsb2.set, xscrollcommand=hsb2.set)
        self.tree_note.grid(row=0, column=0, sticky="nsew")
        vsb2.grid(row=0, column=1, sticky="ns")
        hsb2.grid(row=1, column=0, sticky="ew")
        self.tree_frame_note.grid_rowconfigure(0, weight=1)
        self.tree_frame_note.grid_columnconfigure(0, weight=1)
        self.tree_note.bind("<<TreeviewSelect>>", self._on_select_note)
        self.tree_note.insert("", "end", values=("", "", "", "검색어를 입력하고 Enter 또는 검색 버튼을 클릭하세요", "", ""))

        # ── Wiki 답변 패널 ──────────────────────────────
        self.wiki_frame = tk.Frame(tree_outer, bg="#f8f9fa")
        wiki_hdr = tk.Frame(self.wiki_frame, bg="#f8f9fa")
        wiki_hdr.pack(fill="x", padx=10, pady=(8, 2))
        tk.Label(wiki_hdr, text="Wiki 시맨틱 레이어 검색", bg="#f8f9fa",
                 font=("맑은 고딕", 10, "bold"), fg="#4a90d9").pack(side="left")
        self._lbl_wiki_status = tk.Label(wiki_hdr, text="", bg="#f8f9fa",
                                          font=("맑은 고딕", 9), fg="#888")
        self._lbl_wiki_status.pack(side="right")
        self.txt_wiki = tk.Text(self.wiki_frame, font=("맑은 고딕", 10), wrap="word",
                                 bg="white", relief="solid", bd=1,
                                 state="disabled", padx=10, pady=8)
        wiki_vsb = ttk.Scrollbar(self.wiki_frame, orient="vertical", command=self.txt_wiki.yview)
        self.txt_wiki.configure(yscrollcommand=wiki_vsb.set)
        self.txt_wiki.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(0, 8))
        wiki_vsb.pack(side="right", fill="y", pady=(0, 8), padx=(0, 10))

        # ── 상세 내용 패널 (하단 패널, 크기 조절 가능) ───
        detail_frame = tk.Frame(self._paned, bg="white")
        self._paned.add(detail_frame, stretch="never", minsize=80)

        detail_hdr = tk.Frame(detail_frame, bg="white")
        detail_hdr.pack(fill="x", padx=10, pady=(6, 2))
        tk.Label(detail_hdr, text="선택 내용:", bg="white",
                 font=("맑은 고딕", 9, "bold"), fg="#555").pack(side="left")
        self._btn_copy = tk.Button(detail_hdr, text="복사", command=self._copy_detail,
                                    bg="#e8edf2", fg="#333", font=("맑은 고딕", 8),
                                    relief="flat", padx=10, pady=2, cursor="hand2")
        self._btn_copy.pack(side="right")
        self._lbl_copied = tk.Label(detail_hdr, text="", bg="white",
                                     font=("맑은 고딕", 8), fg="#4a90d9")
        self._lbl_copied.pack(side="right", padx=(0, 6))

        self.txt_detail = tk.Text(detail_frame, font=("맑은 고딕", 10),
                                   relief="flat", bg="white", wrap="word", state="disabled")
        txt_vsb = ttk.Scrollbar(detail_frame, orient="vertical", command=self.txt_detail.yview)
        self.txt_detail.configure(yscrollcommand=txt_vsb.set)
        txt_vsb.pack(side="right", fill="y", padx=(0, 4), pady=(0, 6))
        self.txt_detail.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        # ── 우측 패널: Graph RAG 인터랙티브 그래프 ───────
        hop_outer = tk.Frame(self._outer_paned, bg="#16213e")
        self._outer_paned.add(hop_outer, stretch="never", minsize=220)

        hop_hdr = tk.Frame(hop_outer, bg="#16213e", height=32)
        hop_hdr.pack(fill="x")
        hop_hdr.pack_propagate(False)
        tk.Label(hop_hdr, text="Graph RAG 추론 체인", bg="#16213e", fg="#a0c4ff",
                 font=("맑은 고딕", 9, "bold")).pack(side="left", padx=12, pady=7)
        self._lbl_graph_stat = tk.Label(hop_hdr, text="", bg="#16213e", fg="#557799",
                                         font=("맑은 고딕", 8))
        self._lbl_graph_stat.pack(side="right", padx=6)
        self._btn_full_graph = tk.Button(
            hop_hdr, text="전체 보기", command=self._show_full_graph,
            bg="#2a3a5a", fg="#a0c4ff", font=("맑은 고딕", 8),
            relief="flat", padx=8, pady=2, cursor="hand2"
        )
        self._btn_full_graph.pack(side="right", padx=(4, 0), pady=5)

        # 그래프 / 텍스트 탭 전환 버튼
        tab_bar = tk.Frame(hop_outer, bg="#16213e")
        tab_bar.pack(fill="x")
        self._hop_view = tk.StringVar(value="graph")

        def _switch_hop(mode):
            self._hop_view.set(mode)
            if mode == "graph":
                btn_graph_tab.config(bg="#3a78c9", fg="white")
                btn_text_tab.config(bg="#16213e", fg="#6688aa")
                self._hop_text_frame.pack_forget()
                if self._graph_widget:
                    self._graph_widget.pack(fill="both", expand=True)
            else:
                btn_text_tab.config(bg="#3a78c9", fg="white")
                btn_graph_tab.config(bg="#16213e", fg="#6688aa")
                if self._graph_widget:
                    self._graph_widget.pack_forget()
                self._hop_text_frame.pack(fill="both", expand=True)

        btn_graph_tab = tk.Button(tab_bar, text="그래프", command=lambda: _switch_hop("graph"),
                                   bg="#3a78c9", fg="white", font=("맑은 고딕", 8),
                                   relief="flat", padx=14, pady=3, cursor="hand2")
        btn_graph_tab.pack(side="left", padx=(8, 1), pady=4)
        btn_text_tab = tk.Button(tab_bar, text="텍스트", command=lambda: _switch_hop("text"),
                                  bg="#16213e", fg="#6688aa", font=("맑은 고딕", 8),
                                  relief="flat", padx=14, pady=3, cursor="hand2")
        btn_text_tab.pack(side="left", padx=1, pady=4)

        # GraphWidget 임베드
        try:
            from graph_canvas import GraphWidget
            self._graph_widget = GraphWidget(hop_outer)
            self._graph_widget.pack(fill="both", expand=True)
            self._graph_widget.clear()
        except Exception as e:
            self._graph_widget = None
            tk.Label(hop_outer, text=f"그래프 위젯 로드 실패:\n{e}",
                     bg="#1a1a2e", fg="#f00", font=("맑은 고딕", 9)).pack(pady=20)

        # 텍스트 추론 체인 패널 (초기 숨김)
        self._hop_text_frame = tk.Frame(hop_outer, bg="#1a1a2e")
        self._hop_txt = tk.Text(self._hop_text_frame, font=("맑은 고딕", 9),
                                 bg="#1a1a2e", fg="#c8e0ff", relief="flat",
                                 wrap="word", state="disabled", spacing1=2)
        hop_txt_vsb = ttk.Scrollbar(self._hop_text_frame, orient="vertical",
                                     command=self._hop_txt.yview)
        self._hop_txt.configure(yscrollcommand=hop_txt_vsb.set)
        hop_txt_vsb.pack(side="right", fill="y")
        self._hop_txt.pack(fill="both", expand=True, padx=6, pady=4)
        # 초기 안내
        self._hop_txt.config(state="normal")
        self._hop_txt.insert("1.0", "쪽지를 클릭하면\n텍스트 추론 체인이 표시됩니다.")
        self._hop_txt.config(state="disabled")

        # 스타일
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", font=("맑은 고딕", 10), rowheight=24,
                         background="white", fieldbackground="white")
        style.configure("Treeview.Heading", font=("맑은 고딕", 9, "bold"),
                         background="#e8edf2", foreground="#333")
        style.map("Treeview", background=[("selected", "#c3d9f5")],
                  foreground=[("selected", "#000")])

    # ── placeholder 헬퍼 ──────────────────────────────
    def _clear_placeholder(self, entry, placeholder):
        if entry.get() == placeholder:
            entry.delete(0, "end")
            entry.config(fg="#000")

    def _restore_placeholder(self, entry, placeholder):
        if not entry.get().strip():
            entry.insert(0, placeholder)
            entry.config(fg="#888")

    def _get_date_val(self, entry, placeholder="YYYY-MM-DD"):
        v = entry.get().strip()
        return "" if v == placeholder else v

    # ── 수집 버튼 공통 실행기 ─────────────────────────
    def _run_script(self, script_name, label):
        """스크립트를 서브프로세스로 실행, 진행 상황을 상태바에 표시"""
        # 버튼 비활성화
        for b in self._collect_buttons:
            b.config(state="disabled")
        self._collect_status.config(text=f"  ⏳ {label} 실행 중...")

        def run():
            # script_name에 공백이 있으면 인수 분리 (예: "wiki_build.py ingest")
            parts = script_name.split()
            script = Path(__file__).parent / parts[0]
            cmd_args = parts[1:]
            proc = subprocess.Popen(
                [sys.executable, "-u", str(script)] + cmd_args,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace",
                cwd=str(Path(__file__).parent)
            )
            last_line = ""
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    last_line = line
                    self.after(0, lambda l=line: self._collect_status.config(
                        text=f"  ⏳ {label}: {l[:80]}"))
            proc.wait()
            ok = proc.returncode == 0
            msg = f"  {'✓' if ok else '✗'} {label} 완료" + (f": {last_line[:60]}" if last_line else "")
            self.after(0, lambda: self._collect_status.config(text=msg))
            self.after(0, self._update_stats)
            self.after(0, self._enable_collect_buttons)
            if ok and script_name == "build_index.py":
                # 인덱스 재빌드 후 RAG 체크박스 활성화
                self.after(0, lambda: self._chk_rag.config(state="normal"))

        threading.Thread(target=run, daemon=True).start()

    def _enable_collect_buttons(self):
        for b in self._collect_buttons:
            b.config(state="normal")

    def _run_backup_notes(self):
        self._run_script("backup_notes.py", "쪽지수집")

    def _run_fetch_content(self):
        self._run_script("fetch_full_content.py", "본문수집")

    def _run_batch_download(self):
        self._run_script("batch_download.py", "첨부파일")

    def _run_build_index(self):
        self._run_script("build_index.py", "인덱스재빌드")

    def _run_wiki_ingest(self):
        self._run_script("wiki_build.py ingest", "Wiki빌드")

    # ── Wiki 검색 ─────────────────────────────────────
    def _update_wiki_status(self):
        """Wiki 탭 상태 메시지 갱신."""
        try:
            from pathlib import Path
            wiki_dir = Path(__file__).parent / "wiki"
            people = len(list((wiki_dir / "people").glob("*.md")))
            topics = len(list((wiki_dir / "topics").glob("*.md")))
            timeline = len(list((wiki_dir / "timeline").glob("*.md")))
            if people + topics + timeline == 0:
                msg = "Wiki 없음 — [Wiki빌드] 버튼을 클릭하세요"
            else:
                msg = f"인물 {people}명 · 주제 {topics}개 · 타임라인 {timeline}개"
        except Exception:
            msg = ""
        self._lbl_wiki_status.config(text=msg)

    def _wiki_query(self, q: str) -> tuple:
        """wiki 파일 검색 + (API 있으면) LLM 합성. (result_text, hits) 반환."""
        from pathlib import Path
        import re, os

        wiki_dir = Path(__file__).parent / "wiki"
        if not wiki_dir.exists():
            return "Wiki가 아직 없습니다.\n[Wiki빌드] 버튼을 클릭해 먼저 wiki를 생성하세요.", []

        q_words = [w for w in q.lower().split() if len(w) > 1]
        if not q_words:
            return "검색어를 입력하세요.", []

        hits = []
        for md_path in wiki_dir.rglob("*.md"):
            if md_path.name in ("SCHEMA.md", "index.md", "log.md"):
                continue
            text = md_path.read_text(encoding="utf-8")
            if any(w in text.lower() for w in q_words):
                rel = md_path.relative_to(wiki_dir).as_posix().replace("\\", "/")
                clean = re.sub(r"^---[\s\S]+?---\n", "", text)
                hits.append((rel, clean[:1200]))

        if not hits:
            return (
                f'"{q}"에 관련된 wiki 페이지를 찾지 못했습니다.\n\n'
                "wiki가 최신 상태인지 확인하세요:\n"
                "  → [Wiki빌드] 버튼 클릭 또는\n"
                "  → python wiki_build.py ingest --full"
            ), []

        context = "\n\n".join(
            f"=== {rel} ===\n{content}" for rel, content in hits[:6]
        )
        system = (
            "당신은 학교 행정 메신저 데이터 기반 wiki 검색 도우미입니다. "
            "wiki 내용을 근거로 간결하게 답변하세요. "
            "근거가 없는 추측은 [추론]으로 표시하고, 출처 wiki 파일명을 인용하세요."
        )
        prompt = (
            f"## Wiki 내용\n{context}\n\n"
            f"## 질문\n{q}\n\n"
            "핵심 답변을 먼저 쓰고, 관련 wiki 페이지와 쪽지 코드를 인용하세요."
        )
        sources = "\n".join(f"  · {rel}" for rel, _ in hits[:6])

        # GLM 우선 시도
        glm_key = os.environ.get("GLM_API_KEY", "")
        if glm_key:
            try:
                import zhipuai
                client = zhipuai.ZhipuAI(api_key=glm_key)
                resp = client.chat.completions.create(
                    model="glm-4.7",
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user",   "content": prompt},
                    ],
                    max_tokens=8192,
                )
                answer = (resp.choices[0].message.content or "").strip()
                if answer:
                    return f"{answer}\n\n─ 참조 wiki 페이지 ─\n{sources}", hits
            except Exception:
                pass

        # Anthropic 폴백
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if anthropic_key:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=anthropic_key)
                resp = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=1024,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                )
                answer = resp.content[0].text.strip()
                return f"{answer}\n\n─ 참조 wiki 페이지 ─\n{sources}", hits
            except Exception:
                pass

        # API 없이 wiki 발췌 출력
        lines = [f'"{q}" wiki 검색 결과 ({len(hits)}개 페이지)\n']
        for rel, content in hits[:5]:
            lines.append(f"▶ {rel}")
            for w in q_words:
                idx = content.lower().find(w)
                if idx != -1:
                    snippet = content[max(0, idx-30):idx+200].replace("\n", " ")
                    lines.append(f"  ...{snippet.strip()}...")
                    break
            lines.append("")
        lines.append("※ GLM_API_KEY 또는 ANTHROPIC_API_KEY를 입력하면 LLM이 답변을 합성합니다.")
        return "\n".join(lines), hits

    def _build_wiki_graph(self, q: str, hits: list) -> dict:
        """wiki 검색 결과를 GraphWidget용 dict로 변환."""
        nodes = [{"id": "q", "type": "query", "label": q[:20], "detail": q}]
        edges = []
        people_seen, topic_seen, timeline_seen = set(), set(), set()

        for rel, content in hits[:12]:
            parts = rel.split("/")
            if len(parts) < 2:
                continue
            category, fname = parts[0], parts[1].replace(".md", "")

            if category == "people" and fname not in people_seen:
                people_seen.add(fname)
                # 발송 건수 추출
                m = re.search(r"발송:\s*(\d+)건", content)
                cnt = m.group(1) if m else "?"
                nodes.append({"id": f"p_{fname}", "type": "person",
                               "label": fname, "detail": f"{fname}\n발송 {cnt}건"})
                edges.append({"from": "q", "to": f"p_{fname}",
                               "type": "similarity", "label": "관련 인물"})
                # 이 인물의 관련 주제 연결
                topics_in_page = re.findall(r"\[\[([^\]]+)\]\]", content)
                for t in topics_in_page[:3]:
                    topic_id = f"t_{t}"
                    if t not in topic_seen:
                        topic_seen.add(t)
                        nodes.append({"id": topic_id, "type": "keyword",
                                       "label": t, "detail": f"주제: {t}"})
                    edges.append({"from": f"p_{fname}", "to": topic_id,
                                   "type": "keyword", "label": ""})

            elif category == "topics" and fname not in topic_seen:
                topic_seen.add(fname)
                m = re.search(r"note_count:\s*(\d+)", content)
                cnt = m.group(1) if m else "?"
                nodes.append({"id": f"t_{fname}", "type": "keyword",
                               "label": fname, "detail": f"주제: {fname}\n관련 {cnt}건"})
                edges.append({"from": "q", "to": f"t_{fname}",
                               "type": "keyword", "label": "관련 주제"})

            elif category == "timeline" and fname not in timeline_seen:
                timeline_seen.add(fname)
                nodes.append({"id": f"tl_{fname}", "type": "related",
                               "label": fname, "detail": f"타임라인: {fname}"})
                edges.append({"from": "q", "to": f"tl_{fname}",
                               "type": "person_rel", "label": "기간"})

        return {"nodes": nodes, "edges": edges}

    def _show_wiki_result(self, result: str, q: str, hits: list = None):
        """wiki 결과를 txt_wiki에 표시하고 그래프도 갱신."""
        self.txt_wiki.config(state="normal")
        self.txt_wiki.delete("1.0", "end")
        self.txt_wiki.insert("1.0", result)
        self.txt_wiki.config(state="disabled")
        self.lbl_result_info.config(text=f'Wiki 검색: "{q}"')
        self._update_wiki_status()

        # 그래프 업데이트
        if hits and self._graph_widget:
            graph_data = self._build_wiki_graph(q, hits)
            n = len(graph_data["nodes"])
            e = len(graph_data["edges"])
            self._graph_widget.set_graph(graph_data, layout="radial")
            self._lbl_graph_stat.config(text=f"Wiki 그래프  노드 {n}  엣지 {e}")

    # ── 모드 전환 ─────────────────────────────────────
    def _switch_mode(self, mode):
        self._search_mode = mode
        # 모든 탭 버튼 기본 색으로 초기화
        for b in (self.btn_msg, self.btn_note, self.btn_wiki):
            b.config(bg="#e8edf2", fg="#333")
        # 모든 필터/패널 숨김
        self.row_msg_filter.pack_forget()
        self.row_note_filter.pack_forget()
        self.tree_frame_msg.pack_forget()
        self.tree_frame_note.pack_forget()
        self.wiki_frame.pack_forget()

        if mode == "msg":
            self.btn_msg.config(bg="#4a90d9", fg="white")
            self.row_msg_filter.pack(fill="x", padx=12, pady=(8, 4))
            self.tree_frame_msg.pack(fill="both", expand=True)
        elif mode == "note":
            self.btn_note.config(bg="#4a90d9", fg="white")
            self.row_note_filter.pack(fill="x", padx=12, pady=(8, 4))
            self.tree_frame_note.pack(fill="both", expand=True)
        else:  # wiki
            self.btn_wiki.config(bg="#4a90d9", fg="white")
            self.wiki_frame.pack(fill="both", expand=True)
            self._update_wiki_status()

    # ── 데이터 로드 ───────────────────────────────────
    def _load_rooms(self):
        _, _, _, room_list = get_stats()
        self._room_map = {"전체 채팅방": ""}
        values = ["전체 채팅방"]
        for code, name in room_list:
            display = name if name != code else code[:12] + "..."
            self._room_map[display] = code
            values.append(display)
        self.cmb_room["values"] = values
        self.cmb_room.set("전체 채팅방")

    def _save_api_key(self):
        """입력된 API 키를 환경변수 + config.json에 저장."""
        key = self._api_key_var.get().strip()
        if not key:
            return
        if key.startswith("sk-ant-"):
            os.environ["ANTHROPIC_API_KEY"] = key
            os.environ.pop("GLM_API_KEY", None)
            _save_config("ANTHROPIC_API_KEY", key)
        else:
            os.environ["GLM_API_KEY"] = key
            os.environ.pop("ANTHROPIC_API_KEY", None)
            _save_config("GLM_API_KEY", key)
        self._update_stats()
        self._update_wiki_status()
        self.lbl_result_info.config(text="API 키 저장됨 ✓ (config.json에 유지됩니다)")

    def _update_stats(self):
        msg_total, note_total, rooms, _ = get_stats()
        if self._use_rag.get() and LOCAL_RAG_AVAILABLE:
            mode = "로컬 RAG"
        elif ANTHROPIC_API_KEY:
            mode = "AI 의미검색"
        else:
            mode = "키워드 검색"
        self.lbl_stats.config(text=f"메시지 {msg_total:,}건  |  쪽지 {note_total:,}건  |  채팅방 {rooms}개  |  {mode}")
        self.lbl_mode.config(text=f"검색모드: {mode}")
        self.lbl_mode_note.config(text=f"검색모드: {mode}")

    # ── 검색 ──────────────────────────────────────────
    def _search(self):
        q = self.entry_q.get().strip()
        if not q:
            return
        self.lbl_result_info.config(text="검색 중...")

        if self._search_mode == "wiki":
            def run_wiki():
                result, hits = self._wiki_query(q)
                self.after(0, lambda: self._show_wiki_result(result, q, hits))
            threading.Thread(target=run_wiki, daemon=True).start()
            return

        if self._search_mode == "msg":
            for item in self.tree_msg.get_children():
                self.tree_msg.delete(item)
            sender    = self.entry_sender_msg.get().strip()
            room      = self._room_map.get(self.cmb_room.get(), "")
            date_from = self._get_date_val(self.entry_date_from_msg)
            date_to   = self._get_date_val(self.entry_date_to_msg)
            def run():
                if self._use_rag.get() and LOCAL_RAG_AVAILABLE:
                    if _rag_loading:
                        self.after(0, lambda: self.lbl_result_info.config(text="RAG 모델 로딩 중... 잠시만 기다려주세요"))
                        while _rag_loading:
                            import time; time.sleep(0.3)
                    rows, mode = rag_search_messages(q, room, sender, top_k=100)
                    # RAG 결과에 날짜 후처리 필터
                    df, dt = _parse_date(date_from), _parse_date(date_to)
                    if df: rows = [r for r in rows if (r[5] or "") >= df]
                    if dt: rows = [r for r in rows if (r[5] or "") <= dt]
                elif ANTHROPIC_API_KEY:
                    rows, mode = semantic_search_messages(q, room, sender, date_from, date_to)
                else:
                    rows = search_messages(q, room, sender, date_from, date_to)
                    mode = "키워드"
                self.after(0, lambda: self._show_msg_results(rows, mode, q))
        else:
            for item in self.tree_note.get_children():
                self.tree_note.delete(item)
            sender    = self.entry_sender_note.get().strip()
            nt_map    = {"전체": "all", "받은쪽지": "receive", "보낸쪽지": "send"}
            nt        = nt_map.get(self.cmb_note_type.get(), "all")
            date_from = self._get_date_val(self.entry_date_from_note)
            date_to   = self._get_date_val(self.entry_date_to_note)
            def run():
                if self._use_rag.get() and LOCAL_RAG_AVAILABLE:
                    if _rag_loading:
                        self.after(0, lambda: self.lbl_result_info.config(text="RAG 모델 로딩 중... 잠시만 기다려주세요"))
                        while _rag_loading:
                            import time; time.sleep(0.3)
                    rows, mode = rag_search_notes(q, nt, sender, top_k=100)
                    # RAG 결과에 날짜 후처리 필터
                    df, dt = _parse_date(date_from), _parse_date(date_to)
                    if df: rows = [r for r in rows if (r[6] or "") >= df]
                    if dt: rows = [r for r in rows if (r[6] or "") <= dt + "9"]
                elif ANTHROPIC_API_KEY:
                    rows, mode = semantic_search_notes(q, nt, sender, date_from, date_to)
                else:
                    rows = search_notes(q, nt, sender, date_from, date_to)
                    mode = "키워드"
                self.after(0, lambda: self._show_note_results(rows, mode, q))

        threading.Thread(target=run, daemon=True).start()

    def _show_msg_results(self, rows, mode, q):
        for item in self.tree_msg.get_children():
            self.tree_msg.delete(item)
        if not rows:
            self.tree_msg.insert("", "end", values=("", "", f'"{q}" 검색 결과 없음', "", ""))
            self.lbl_result_info.config(text=f"결과 없음  ({mode})")
            return
        for r in rows:
            room_code, room_name, sender, content, msg_time, msg_date = r
            display_room = room_name if room_name and room_name != room_code else room_code[:14]
            self.tree_msg.insert("", "end", values=(sender, display_room, content, msg_time, msg_date))
        self.lbl_result_info.config(text=f"{len(rows)}건 결과  ({mode})")
        self._update_stats()

    def _show_note_results(self, rows, mode, q):
        self._last_note_rows = rows   # 전체 보기용 저장
        self._last_note_query = q
        for item in self.tree_note.get_children():
            self.tree_note.delete(item)
        if not rows:
            self.tree_note.insert("", "end", values=("", "", "", f'"{q}" 검색 결과 없음', "", ""))
            self.lbl_result_info.config(text=f"결과 없음  ({mode})")
            return
        for r in rows:
            note_code, note_type, sender, receiver, title, content, note_date, read_yn, file_cnt = r
            type_label = "받은" if note_type == "receive" else "보낸"
            display_content = title or content[:60]
            date_str = fmt_note_date(note_date)
            file_str = f"📎{file_cnt}" if file_cnt else ""
            self.tree_note.insert("", "end",
                values=(type_label, sender, receiver, display_content, date_str, file_str),
                tags=(note_code,))
        self.lbl_result_info.config(text=f"{len(rows)}건 결과  ({mode})")
        self._update_stats()

    def _on_select_msg(self, event):
        sel = self.tree_msg.selection()
        if not sel:
            return
        vals = self.tree_msg.item(sel[0], "values")
        if len(vals) >= 5:
            sender, room, content, time_, date_ = vals
            detail = f"[{date_} {time_}] {sender}  ({room})\n{content}"
            self._set_detail(detail)

    def _on_select_note(self, event):
        sel = self.tree_note.selection()
        if not sel:
            return
        vals = self.tree_note.item(sel[0], "values")
        tags = self.tree_note.item(sel[0], "tags")
        if len(vals) >= 6:
            type_label, sender, receiver, title, date_, files = vals
            # DB에서 전체 내용 가져오기
            note_code = tags[0] if tags else ""
            content = title
            if note_code:
                try:
                    conn = sqlite3.connect(DB_PATH)
                    row = conn.execute(
                        "SELECT title, content FROM notes WHERE note_code=?", (note_code,)
                    ).fetchone()
                    conn.close()
                    if row:
                        content = f"[제목] {row[0]}\n{row[1]}" if row[0] != row[1] else row[1]
                except:
                    pass
            detail = f"[{date_}] {type_label}쪽지  {sender} → {receiver}  {files}\n{content}"
            self._set_detail(detail)
            if note_code and self._graph_widget:
                query = self.entry_q.get().strip()
                threading.Thread(
                    target=self._update_graph,
                    args=(note_code, query),
                    daemon=True
                ).start()

    def _show_full_graph(self):
        """검색 결과 전체를 하나의 그래프로 표시"""
        rows  = self._last_note_rows
        query = self._last_note_query
        if not rows or not self._graph_widget:
            return
        self._btn_full_graph.config(state="disabled")

        def run():
            try:
                from graph_rag import get_full_graph_data
                try:
                    from local_rag import _last_note_scores
                    scores = dict(_last_note_scores)
                except Exception:
                    scores = {}
                data = get_full_graph_data(rows, query, scores)
                n_nodes = len(data.get("nodes", []))
                n_edges = len(data.get("edges", []))
                self.after(0, lambda: self._graph_widget.set_graph(data))
                self.after(0, lambda: self._lbl_graph_stat.config(
                    text=f"노드 {n_nodes}  엣지 {n_edges}"
                ))
            except Exception as e:
                self.after(0, lambda: self._lbl_graph_stat.config(text=f"오류: {e}"))
            self.after(0, lambda: self._btn_full_graph.config(state="normal"))

        threading.Thread(target=run, daemon=True).start()

    def _update_graph(self, note_code, query):
        """백그라운드에서 그래프 + 텍스트 체인 생성 후 업데이트"""
        try:
            from graph_rag import get_hop_graph_data, get_hop_chain_text
            try:
                from local_rag import _last_note_scores
                score = _last_note_scores.get(note_code)
            except Exception:
                score = None
            q = query or "(쿼리 없음)"
            data = get_hop_graph_data(note_code, q, sim_score=score)
            text = get_hop_chain_text(note_code, q, sim_score=score)
            n_nodes = len(data.get("nodes", []))
            n_edges = len(data.get("edges", []))
            if self._graph_widget:
                self.after(0, lambda: self._graph_widget.set_graph(data))
            self.after(0, lambda: self._set_hop_text(text))
            self.after(0, lambda: self._lbl_graph_stat.config(
                text=f"노드 {n_nodes}  엣지 {n_edges}"
            ))
        except Exception as e:
            self.after(0, lambda: self._lbl_graph_stat.config(text=f"오류: {e}"))

    def _set_hop_text(self, text):
        self._hop_txt.config(state="normal")
        self._hop_txt.delete("1.0", "end")
        self._hop_txt.insert("1.0", text)
        self._hop_txt.config(state="disabled")

    def _set_detail(self, text):
        self.txt_detail.config(state="normal")
        self.txt_detail.delete("1.0", "end")
        self.txt_detail.insert("1.0", text)
        self.txt_detail.config(state="disabled")

    def _copy_detail(self):
        text = self.txt_detail.get("1.0", "end-1c").strip()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self._lbl_copied.config(text="복사됨 ✓")
        self.after(2000, lambda: self._lbl_copied.config(text=""))


if __name__ == "__main__":
    app = App()
    app._switch_mode("msg")
    # 상세 패널 초기 높이 150px 확보
    app.update_idletasks()
    # 상하 분할: 하단 상세 패널 150px
    total_h = app._paned.winfo_height()
    if total_h > 200:
        app._paned.sash_place(0, 0, total_h - 150)
    # 좌우 분할: 우측 Graph RAG 패널 320px
    total_w = app._outer_paned.winfo_width()
    if total_w > 500:
        app._outer_paned.sash_place(0, total_w - 320, 0)
    app.mainloop()
