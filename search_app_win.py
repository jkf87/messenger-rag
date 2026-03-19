"""
메시지/쪽지 RAG 검색 - Windows 앱
실행: python search_app_win.py
"""
import sys, sqlite3, os, threading, re
from pathlib import Path
import tkinter as tk
from tkinter import ttk

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = Path(__file__).parent / "messages.db"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

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
def search_messages(q, room="", sender=""):
    conn = sqlite3.connect(DB_PATH)
    sql    = "SELECT room_code,room_name,sender,content,msg_time,msg_date FROM messages WHERE content LIKE ?"
    params = [f"%{q}%"]
    if room:   sql += " AND room_code=?";    params.append(room)
    if sender: sql += " AND sender LIKE ?";  params.append(f"%{sender}%")
    sql += " ORDER BY msg_date DESC, msg_time DESC LIMIT 200"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows

def search_notes(q, note_type="all", sender=""):
    conn = sqlite3.connect(DB_PATH)
    try:
        sql    = "SELECT note_code,note_type,sender,receiver,title,content,note_date,read_yn,file_cnt FROM notes WHERE (title LIKE ? OR content LIKE ?)"
        params = [f"%{q}%", f"%{q}%"]
        if note_type == "receive": sql += " AND note_type='receive'"
        elif note_type == "send":  sql += " AND note_type='send'"
        if sender: sql += " AND sender LIKE ?"; params.append(f"%{sender}%")
        sql += " ORDER BY note_date DESC LIMIT 200"
        rows = conn.execute(sql, params).fetchall()
    except:
        rows = []
    conn.close()
    return rows

def semantic_search_messages(q, room="", sender=""):
    import anthropic
    conn = sqlite3.connect(DB_PATH)
    sql    = "SELECT room_code,room_name,sender,content,msg_time,msg_date FROM messages WHERE content LIKE ?"
    params = [f"%{q}%"]
    if room:   sql += " AND room_code=?"; params.append(room)
    if sender: sql += " AND sender LIKE ?"; params.append(f"%{sender}%")
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

def semantic_search_notes(q, note_type="all", sender=""):
    import anthropic
    rows = search_notes(q, note_type, sender)
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

        # 필터 행 (메시지용)
        self.row_msg_filter = tk.Frame(self.search_frame, bg="white")
        self.row_msg_filter.pack(fill="x", padx=12, pady=(8, 4))

        tk.Label(self.row_msg_filter, text="채팅방:", bg="white", font=("맑은 고딕", 9)).pack(side="left")
        self.cmb_room = ttk.Combobox(self.row_msg_filter, width=20, font=("맑은 고딕", 9), state="readonly")
        self.cmb_room.pack(side="left", padx=(4, 16))

        tk.Label(self.row_msg_filter, text="발신자:", bg="white", font=("맑은 고딕", 9)).pack(side="left")
        self.entry_sender_msg = tk.Entry(self.row_msg_filter, width=14, font=("맑은 고딕", 9), relief="solid", bd=1)
        self.entry_sender_msg.pack(side="left", padx=(4, 0), ipady=3)

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
        self.entry_sender_note.pack(side="left", padx=(4, 0), ipady=3)

        self.lbl_mode_note = tk.Label(self.row_note_filter, text="", bg="white", font=("맑은 고딕", 9), fg="#888")
        self.lbl_mode_note.pack(side="right")

        # 결과 상태
        self.lbl_result_info = tk.Label(self, text="", bg="#f0f2f5",
                                         font=("맑은 고딕", 9), fg="#666", anchor="w")
        self.lbl_result_info.pack(fill="x", padx=14, pady=(6, 2))

        # TreeView (메시지용)
        self.tree_frame_msg = tk.Frame(self, bg="#f0f2f5")
        self.tree_frame_msg.pack(fill="both", expand=True, padx=12, pady=(0, 4))

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
        self.tree_frame_note = tk.Frame(self, bg="#f0f2f5")

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

        # 상세 내용 패널
        detail_frame = tk.Frame(self, bg="white", height=100)
        detail_frame.pack(fill="x", padx=12, pady=(0, 10))
        detail_frame.pack_propagate(False)
        tk.Label(detail_frame, text="선택 내용:", bg="white",
                 font=("맑은 고딕", 9, "bold"), fg="#555").pack(anchor="w", padx=10, pady=(6, 2))
        self.txt_detail = tk.Text(detail_frame, height=4, font=("맑은 고딕", 10),
                                   relief="flat", bg="white", wrap="word", state="disabled")
        self.txt_detail.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        # 스타일
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", font=("맑은 고딕", 10), rowheight=24,
                         background="white", fieldbackground="white")
        style.configure("Treeview.Heading", font=("맑은 고딕", 9, "bold"),
                         background="#e8edf2", foreground="#333")
        style.map("Treeview", background=[("selected", "#c3d9f5")],
                  foreground=[("selected", "#000")])

    # ── 모드 전환 ─────────────────────────────────────
    def _switch_mode(self, mode):
        self._search_mode = mode
        if mode == "msg":
            self.btn_msg.config(bg="#4a90d9", fg="white")
            self.btn_note.config(bg="#e8edf2", fg="#333")
            self.row_msg_filter.pack(fill="x", padx=12, pady=(8, 4))
            self.row_note_filter.pack_forget()
            self.tree_frame_note.pack_forget()
            self.tree_frame_msg.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        else:
            self.btn_note.config(bg="#4a90d9", fg="white")
            self.btn_msg.config(bg="#e8edf2", fg="#333")
            self.row_note_filter.pack(fill="x", padx=12, pady=(8, 4))
            self.row_msg_filter.pack_forget()
            self.tree_frame_msg.pack_forget()
            self.tree_frame_note.pack(fill="both", expand=True, padx=12, pady=(0, 4))

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

    def _update_stats(self):
        msg_total, note_total, rooms, _ = get_stats()
        mode = "AI 의미검색" if ANTHROPIC_API_KEY else "키워드 검색"
        self.lbl_stats.config(text=f"메시지 {msg_total:,}건  |  쪽지 {note_total:,}건  |  채팅방 {rooms}개  |  {mode}")
        self.lbl_mode.config(text=f"검색모드: {mode}")
        self.lbl_mode_note.config(text=f"검색모드: {mode}")

    # ── 검색 ──────────────────────────────────────────
    def _search(self):
        q = self.entry_q.get().strip()
        if not q:
            return
        self.lbl_result_info.config(text="검색 중...")

        if self._search_mode == "msg":
            for item in self.tree_msg.get_children():
                self.tree_msg.delete(item)
            sender = self.entry_sender_msg.get().strip()
            room   = self._room_map.get(self.cmb_room.get(), "")
            def run():
                if ANTHROPIC_API_KEY:
                    rows, mode = semantic_search_messages(q, room, sender)
                else:
                    rows = search_messages(q, room, sender)
                    mode = "키워드"
                self.after(0, lambda: self._show_msg_results(rows, mode, q))
        else:
            for item in self.tree_note.get_children():
                self.tree_note.delete(item)
            sender = self.entry_sender_note.get().strip()
            nt_map = {"전체": "all", "받은쪽지": "receive", "보낸쪽지": "send"}
            nt     = nt_map.get(self.cmb_note_type.get(), "all")
            def run():
                if ANTHROPIC_API_KEY:
                    rows, mode = semantic_search_notes(q, nt, sender)
                else:
                    rows = search_notes(q, nt, sender)
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
        if len(vals) >= 5:
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

    def _set_detail(self, text):
        self.txt_detail.config(state="normal")
        self.txt_detail.delete("1.0", "end")
        self.txt_detail.insert("1.0", text)
        self.txt_detail.config(state="disabled")


if __name__ == "__main__":
    app = App()
    # 기본 메시지 모드로 시작
    app._switch_mode("msg")
    app.mainloop()
