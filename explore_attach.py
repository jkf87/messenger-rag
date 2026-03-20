# -*- coding: utf-8 -*-
"""쪽지 첨부파일 API 탐색"""
import sys, json, sqlite3, urllib.request
from pathlib import Path
from websocket import create_connection

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = Path(__file__).parent / "messages.db"
CDP_URL = "http://127.0.0.1:9000/json"

def ev_sync(ws, id_, expr):
    ws.send(json.dumps({"id": id_, "method": "Runtime.evaluate", "params": {"expression": expr}}))
    return json.loads(ws.recv()).get("result", {}).get("result", {}).get("value", "")

pages = json.loads(urllib.request.urlopen(CDP_URL, timeout=3).read())
main = next(p for p in pages if "main" in p.get("url", ""))
ws = create_connection(main["webSocketDebuggerUrl"], timeout=10)

# 첨부파일 있는 쪽지 5개
conn = sqlite3.connect(DB_PATH)
rows = conn.execute("SELECT note_code, title, file_cnt FROM notes WHERE file_cnt > 0 LIMIT 5").fetchall()
conn.close()

print("=== 첨부파일 있는 쪽지 ===")
for r in rows:
    print(f"  code={r[0]}  files={r[2]}  title={r[1][:40]}")

note_code = rows[0][0]
print(f"\n=== API 탐색: {note_code} ===")

# 시도할 엔드포인트 목록
endpoints = [
    ("noteFileList",   f"{{noteCode:'{note_code}'}}"),
    ("noteDetail",     f"{{noteCode:'{note_code}'}}"),
    ("noteView",       f"{{noteCode:'{note_code}'}}"),
    ("fileList",       f"{{noteCode:'{note_code}'}}"),
    ("attachList",     f"{{noteCode:'{note_code}'}}"),
]

for idx, (ep, data) in enumerate(endpoints):
    url = f"/ezmaru/pc/note/{ep}"
    result = ev_sync(ws, idx+20, f"""
var r='';
$.ajax({{
    url:'{url}',
    type:'POST', async:false,
    data:{data},
    success:function(d){{r='OK:'+JSON.stringify(d);}},
    error:function(e){{r='ERR:'+e.status;}}
}});
r
""")
    print(f"\n[{url}]")
    print(result[:600])

# noteDetail 도 별도로 확인
print("\n=== noteDetail 전체 응답 ===")
result = ev_sync(ws, 50, f"""
var r='';
$.ajax({{
    url:'/ezmaru/pc/note/noteDetail',
    type:'POST', async:false,
    data:{{NTE_CODE:'{note_code}'}},
    success:function(d){{r='OK:'+JSON.stringify(d);}},
    error:function(e){{r='ERR:'+e.status;}}
}});
r
""")
print(result[:800])

ws.close()
