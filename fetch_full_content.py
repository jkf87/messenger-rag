# -*- coding: utf-8 -*-
"""
쪽지 전체 본문 수집 - API 직접 배치 호출 방식
- $.ajax → /pc/note/noteDetail (암호화 불필요)
- JS에서 모든 코드 순회 후 Python에서 일괄 DB 저장
- 예상 소요: 약 2~3분
"""
import sys, json, urllib.request, sqlite3, time, re
from pathlib import Path
from websocket import create_connection

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CDP_URL = "http://127.0.0.1:9000/json"
DB_PATH = Path(__file__).parent / "messages.db"

def get_note_ws():
    pages = json.loads(urllib.request.urlopen(CDP_URL, timeout=3).read())
    for p in pages:
        if "noteDetail" in p.get("url", "") and "webSocketDebuggerUrl" in p:
            return p["webSocketDebuggerUrl"]
    return None

def js(ws, id_, expr, timeout=120):
    ws.send(json.dumps({"id": id_, "method": "Runtime.evaluate", "params": {"expression": expr}}))
    ws.settimeout(timeout)
    return json.loads(ws.recv()).get("result", {}).get("result", {}).get("value", "")

def clean(text):
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return re.sub(r'\n{3,}', '\n\n', text).strip()

# ── 수집 대상 ──────────────────────────────────────────
conn = sqlite3.connect(DB_PATH)
notes = conn.execute(
    "SELECT note_code FROM notes WHERE length(content) <= 100 ORDER BY note_date DESC"
).fetchall()
conn.close()
codes = [r[0] for r in notes]
print(f"업데이트 대상: {len(codes)}건")

# ── noteDetail WS 연결 ────────────────────────────────
print("noteDetail 창 대기 중...")
ws_url = None
for _ in range(30):
    ws_url = get_note_ws()
    if ws_url: break
    time.sleep(2)

if not ws_url:
    print("ERROR: noteDetail 창을 열어두세요.")
    exit(1)

ws = create_connection(ws_url, timeout=120)
ctx_root = js(ws, 0, "$('input[name=ContextRoot]').val()")
print(f"연결됨! ContextRoot={ctx_root}\n")

# ── JS에서 전체 배치 AJAX 호출 ────────────────────────
# UI 렌더링 없이 API만 직접 호출 → 0.15s/건
CHUNK = 100   # 100건씩 나눠서 처리 (JS 메모리 부담 방지)
total_saved = 0

for chunk_start in range(0, len(codes), CHUNK):
    chunk = codes[chunk_start:chunk_start + CHUNK]
    codes_js = json.dumps(chunk)

    print(f"배치 {chunk_start+1}~{chunk_start+len(chunk)}건 API 호출 중...")

    r = js(ws, 10, f"""
    (function() {{
        var codes = {codes_js};
        var ctx   = $('input[name=ContextRoot]').val();
        var results = {{}};
        var errors  = [];

        codes.forEach(function(code) {{
            $.ajax({{
                url: ctx + '/pc/note/noteDetail',
                type: 'POST',
                async: false,
                data: {{ nteCode: code }},
                success: function(d) {{
                    var item = d.LIST || {{}};
                    var content = item.NTE_CONTENT || item.CONTENTS || '';
                    results[code] = content;
                }},
                error: function(e) {{
                    errors.push(code + ':' + e.status);
                }}
            }});
        }});

        return JSON.stringify({{ results: results, errors: errors }});
    }})()
    """, timeout=300)

    try:
        data = json.loads(r)
    except:
        print(f"  파싱 실패: {r[:100]}")
        continue

    results = data.get("results", {})
    errors  = data.get("errors", [])

    # DB 저장
    conn = sqlite3.connect(DB_PATH)
    saved = 0
    for code, content in results.items():
        content = clean(content)
        if content:
            conn.execute("UPDATE notes SET content=? WHERE note_code=?", (content, code))
            saved += 1
    conn.commit()
    conn.close()

    total_saved += saved
    print(f"  저장: {saved}건 | 오류: {len(errors)}건 | 누적: {total_saved}건")
    if errors:
        print(f"  오류 코드: {errors[:3]}")

ws.close()
print(f"\n완료! 총 {total_saved}건 업데이트")
