# -*- coding: utf-8 -*-
"""noteDetail API 직접 호출 테스트 - 암호화 없이 되는지 확인"""
import sys, json, urllib.request, sqlite3
from pathlib import Path
from websocket import create_connection

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CDP_URL = "http://127.0.0.1:9000/json"
DB_PATH = Path(__file__).parent / "messages.db"

pages = json.loads(urllib.request.urlopen(CDP_URL, timeout=3).read())
ws_url = next(p['webSocketDebuggerUrl'] for p in pages if 'noteDetail' in p.get('url','') and 'webSocketDebuggerUrl' in p)
ws = create_connection(ws_url, timeout=15)

def js(id_, expr):
    ws.send(json.dumps({"id": id_, "method": "Runtime.evaluate", "params": {"expression": expr}}))
    return json.loads(ws.recv()).get("result", {}).get("result", {}).get("value", "")

# 테스트용 노트 코드 가져오기
conn = sqlite3.connect(DB_PATH)
sample = conn.execute("SELECT note_code, title FROM notes WHERE length(content) <= 100 LIMIT 1").fetchone()
conn.close()
note_code, title = sample
print(f"테스트 쪽지: {title[:40]}")
print(f"코드: {note_code}\n")

# 방법1: $.ajax 직접 (암호화 없이)
print("=== 방법1: $.ajax 직접 호출 ===")
r1 = js(1, f"""
var result = 'pending';
$.ajax({{
    url: $('input[name=ContextRoot]').val() + '/pc/note/noteDetail',
    type: 'POST',
    async: false,
    data: {{ nteCode: '{note_code}' }},
    success: function(d) {{ result = JSON.stringify(d).substring(0,300); }},
    error: function(e) {{ result = 'ERR:' + e.status + ' ' + e.responseText.substring(0,100); }}
}});
result
""")
print(f"결과: {r1}\n")

# 방법2: noteList에 pageSize=1로 특정 코드만 조회
print("=== 방법2: noteList + 전체 content 가능한지 ===")
r2 = js(2, f"""
var result = 'pending';
$.ajax({{
    url: $('input[name=ContextRoot]').val() + '/pc/note/noteList',
    type: 'POST',
    async: false,
    data: {{ pageSize: 1, pageNo: 1, noteType: 'receive', nteCode: '{note_code}' }},
    success: function(d) {{ result = JSON.stringify(d).substring(0,400); }},
    error: function(e) {{ result = 'ERR:' + e.status; }}
}});
result
""")
print(f"결과: {r2}\n")

# 방법3: Python urllib로 직접 POST (쿠키 사용)
print("=== 방법3: Python urllib 직접 POST ===")
cookie = js(3, "document.cookie")
ctx_root = js(4, "$('input[name=ContextRoot]').val()")
print(f"ContextRoot: {ctx_root}")

import urllib.parse
data = urllib.parse.urlencode({'nteCode': note_code}).encode()
req = urllib.request.Request(
    f"http://stmsg.cbe.go.kr:7880{ctx_root}/pc/note/noteDetail",
    data=data, method='POST'
)
req.add_header("Cookie", cookie)
req.add_header("Content-Type", "application/x-www-form-urlencoded")
req.add_header("User-Agent", "Mozilla/5.0")
req.add_header("X-Requested-With", "XMLHttpRequest")
try:
    resp = urllib.request.urlopen(req, timeout=10)
    body = resp.read().decode('utf-8', errors='replace')
    print(f"응답 ({len(body)}자): {body[:300]}")
except Exception as e:
    print(f"오류: {e}")

ws.close()
