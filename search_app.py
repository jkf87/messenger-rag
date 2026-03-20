"""
메시지 RAG 검색 서브 앱
- backup.py로 저장된 메시지를 검색
- 브라우저에서 http://127.0.0.1:8765 접속
- python search_app.py
"""
import sys, sqlite3, os
from pathlib import Path
from flask import Flask, request, jsonify, render_template_string

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = Path(__file__).parent / "messages.db"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
PORT = 8765

app = Flask(__name__)

# ── HTML UI ──────────────────────────────────────────
UI_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>메시지 검색</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Malgun Gothic', sans-serif; background: #f0f2f5; color: #333; }
  .header { background: #4a90d9; color: #fff; padding: 16px 24px; }
  .header h1 { font-size: 18px; }
  .header small { font-size: 12px; opacity: 0.8; }
  .container { max-width: 900px; margin: 24px auto; padding: 0 16px; }
  .search-box { background: #fff; border-radius: 8px; padding: 20px; box-shadow: 0 1px 4px rgba(0,0,0,.1); margin-bottom: 16px; }
  .search-row { display: flex; gap: 8px; }
  input[type=text] { flex: 1; padding: 10px 14px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; }
  button { padding: 10px 20px; background: #4a90d9; color: #fff; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; }
  button:hover { background: #357abd; }
  .filters { margin-top: 10px; display: flex; gap: 12px; align-items: center; font-size: 13px; }
  .filters select { padding: 5px 8px; border: 1px solid #ddd; border-radius: 4px; font-size: 13px; }
  .stats { background: #fff; border-radius: 8px; padding: 12px 20px; font-size: 13px; color: #666; margin-bottom: 16px; box-shadow: 0 1px 4px rgba(0,0,0,.1); }
  .result-item { background: #fff; border-radius: 8px; padding: 14px 18px; margin-bottom: 10px; box-shadow: 0 1px 4px rgba(0,0,0,.08); border-left: 3px solid #4a90d9; }
  .result-meta { font-size: 12px; color: #888; margin-bottom: 6px; }
  .result-meta span { margin-right: 12px; }
  .result-sender { font-weight: bold; color: #4a90d9; }
  .result-text { font-size: 14px; line-height: 1.6; }
  .highlight { background: #fff3cd; border-radius: 2px; padding: 0 2px; }
  .empty { text-align: center; padding: 40px; color: #aaa; font-size: 14px; }
  #status { margin-top: 8px; font-size: 12px; color: #888; }
  .mode-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; }
  .mode-ai { background: #e8f4fd; color: #1a7ac7; }
  .mode-kw { background: #f0f0f0; color: #666; }
</style>
</head>
<body>
<div class="header">
  <h1>충북소통메신저 검색</h1>
  <small id="headerStats">로딩 중...</small>
</div>
<div class="container">
  <div class="search-box">
    <div class="search-row">
      <input type="text" id="q" placeholder="검색어 입력 (예: 회의 일정, 파일 전송...)" onkeydown="if(event.key==='Enter')search()">
      <button onclick="search()">검색</button>
    </div>
    <div class="filters">
      <label>채팅방: <select id="roomFilter"><option value="">전체</option></select></label>
      <label>발신자: <input type="text" id="senderFilter" style="width:100px;padding:4px 8px;"></label>
      <span id="modeLabel"></span>
    </div>
    <div id="status"></div>
  </div>
  <div id="results"></div>
</div>
<script>
async function loadStats() {
  const r = await fetch('/api/stats');
  const d = await r.json();
  document.getElementById('headerStats').textContent =
    `총 ${d.messages}건 메시지 | ${d.rooms}개 채팅방`;
  const sel = document.getElementById('roomFilter');
  (d.room_list||[]).forEach(function(rm){
    var opt = document.createElement('option');
    opt.value = rm.code; opt.textContent = rm.name || rm.code;
    sel.appendChild(opt);
  });
  document.getElementById('modeLabel').innerHTML =
    d.ai_enabled
      ? '<span class="mode-badge mode-ai">AI 의미검색</span>'
      : '<span class="mode-badge mode-kw">키워드 검색</span>';
}

async function search() {
  const q = document.getElementById('q').value.trim();
  if(!q) return;
  const room = document.getElementById('roomFilter').value;
  const sender = document.getElementById('senderFilter').value.trim();
  document.getElementById('status').textContent = '검색 중...';
  document.getElementById('results').innerHTML = '';

  const params = new URLSearchParams({q});
  if(room) params.set('room', room);
  if(sender) params.set('sender', sender);

  const r = await fetch('/api/search?' + params);
  const d = await r.json();
  document.getElementById('status').textContent = `${d.results.length}건 결과 (${d.mode})`;

  if(d.results.length === 0){
    document.getElementById('results').innerHTML = '<div class="empty">결과 없음</div>';
    return;
  }

  const re = new RegExp(q.replace(/[.*+?^${}()|[\\]\\\\]/g,'\\\\$&'),'gi');
  document.getElementById('results').innerHTML = d.results.map(function(item){
    const hl = item.content.replace(re, '<span class="highlight">$&</span>');
    return `<div class="result-item">
      <div class="result-meta">
        <span class="result-sender">${item.sender}</span>
        <span>${item.room_name || item.room_code}</span>
        <span>${item.msg_date} ${item.msg_time}</span>
      </div>
      <div class="result-text">${hl}</div>
    </div>`;
  }).join('');
}

loadStats();
document.getElementById('q').focus();
</script>
</body>
</html>"""

# ── API ──────────────────────────────────────────────
@app.route("/")
def index():
    return render_template_string(UI_HTML)

@app.route("/api/stats")
def stats():
    conn = sqlite3.connect(DB_PATH)
    msgs  = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    rooms = conn.execute("SELECT COUNT(DISTINCT room_code) FROM messages").fetchone()[0]
    room_list = conn.execute(
        "SELECT room_code, room_name FROM messages GROUP BY room_code ORDER BY room_name"
    ).fetchall()
    conn.close()
    return jsonify({
        "messages": msgs,
        "rooms": rooms,
        "room_list": [{"code":r[0],"name":r[1]} for r in room_list],
        "ai_enabled": bool(ANTHROPIC_API_KEY)
    })

@app.route("/api/search")
def search():
    q      = request.args.get("q","").strip()
    room   = request.args.get("room","")
    sender = request.args.get("sender","")
    if not q:
        return jsonify({"results":[],"mode":"none"})

    if ANTHROPIC_API_KEY:
        results, mode = semantic_search(q, room, sender)
    else:
        results, mode = keyword_search(q, room, sender)

    return jsonify({"results": results, "mode": mode, "query": q})

def keyword_search(q, room="", sender=""):
    conn = sqlite3.connect(DB_PATH)
    sql  = "SELECT room_code,room_name,sender,content,msg_time,msg_date FROM messages WHERE content LIKE ?"
    params = [f"%{q}%"]
    if room:
        sql += " AND room_code=?"; params.append(room)
    if sender:
        sql += " AND sender LIKE ?"; params.append(f"%{sender}%")
    sql += " ORDER BY msg_date DESC, msg_time DESC LIMIT 50"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [
        {"room_code":r[0],"room_name":r[1],"sender":r[2],"content":r[3],"msg_time":r[4],"msg_date":r[5]}
        for r in rows
    ], "keyword"

def semantic_search(q, room="", sender=""):
    import anthropic
    conn = sqlite3.connect(DB_PATH)
    sql  = "SELECT room_code,room_name,sender,content,msg_time,msg_date FROM messages WHERE content LIKE ?"
    params = [f"%{q}%"]
    if room:   sql += " AND room_code=?"; params.append(room)
    if sender: sql += " AND sender LIKE ?"; params.append(f"%{sender}%")
    sql += " ORDER BY msg_date DESC LIMIT 100"
    rows = conn.execute(sql, params).fetchall()

    # 키워드 결과 부족하면 최근 메시지 보강
    if len(rows) < 10:
        extra_sql = "SELECT room_code,room_name,sender,content,msg_time,msg_date FROM messages ORDER BY msg_date DESC, msg_time DESC LIMIT 200"
        extra = conn.execute(extra_sql).fetchall()
        seen  = {(r[0],r[3]) for r in rows}
        rows += [r for r in extra if (r[0],r[3]) not in seen][:100]
    conn.close()

    if not rows:
        return [], "ai-empty"

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    candidates = "\n".join(
        f"[{i}] {r[1]}|{r[2]}|{r[3][:80]}|{r[4]}"
        for i, r in enumerate(rows[:80])
    )
    prompt = f'다음 메시지 목록에서 "{q}"와 관련된 것을 관련성 순으로 최대 15개 번호만 반환 (쉼표 구분):\n{candidates}'
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=200,
            messages=[{"role":"user","content":prompt}]
        )
        indices = [int(x.strip()) for x in resp.content[0].text.split(",") if x.strip().isdigit()]
        results = [
            {"room_code":rows[i][0],"room_name":rows[i][1],"sender":rows[i][2],
             "content":rows[i][3],"msg_time":rows[i][4],"msg_date":rows[i][5]}
            for i in indices if i < len(rows)
        ]
        return results, "ai-semantic"
    except Exception as e:
        print(f"[AI 검색 오류] {e}")
        return keyword_search(q, room, sender)[0], "keyword-fallback"

# ── 메인 ────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 50)
    print("메시지 검색 앱")
    print(f"브라우저에서 열기: http://127.0.0.1:{PORT}")
    if ANTHROPIC_API_KEY:
        print("AI 의미 검색 활성화")
    else:
        print("[!] ANTHROPIC_API_KEY 미설정 - 키워드 검색만 사용")
    print("Ctrl+C로 종료")
    print("=" * 50)

    import webbrowser, threading
    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    app.run(host="127.0.0.1", port=PORT, debug=False)
