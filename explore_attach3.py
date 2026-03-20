# -*- coding: utf-8 -*-
"""쪽지 첨부파일 API 전체 응답 확인"""
import sys, json, sqlite3, urllib.request
from pathlib import Path
from websocket import create_connection

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = Path(__file__).parent / "messages.db"
CDP_URL  = "http://127.0.0.1:9000/json"

def js(ws, id_, expr):
    ws.send(json.dumps({"id": id_, "method": "Runtime.evaluate",
                        "params": {"expression": expr}}))
    return json.loads(ws.recv()).get("result", {}).get("result", {}).get("value", "")

pages = json.loads(urllib.request.urlopen(CDP_URL, timeout=3).read())
main  = next(p for p in pages if "main" in p.get("url", ""))
ws    = create_connection(main["webSocketDebuggerUrl"], timeout=10)

conn = sqlite3.connect(DB_PATH)
# 첨부파일 많은 것부터
rows = conn.execute("SELECT note_code, title, file_cnt FROM notes WHERE file_cnt > 0 ORDER BY file_cnt DESC LIMIT 5").fetchall()
conn.close()

for i, (note_code, title, file_cnt) in enumerate(rows):
    print(f"\n{'='*60}")
    print(f"쪽지: {title[:40]}  (첨부:{file_cnt}개)")
    print(f"code: {note_code}")

    # 1. /ezmaru/pc/file/fileList 전체 응답
    r = js(ws, i*10+1, f"""
var r='';
$.ajax({{url:'/ezmaru/pc/file/fileList',type:'POST',async:false,
data:{{note_code:'{note_code}'}},
success:function(d){{r=JSON.stringify(d);}},
error:function(e){{r='ERR:'+e.status;}}
}});
r
""")
    print(f"\n[/ezmaru/pc/file/fileList] 응답:")
    try:
        parsed = json.loads(r)
        print(json.dumps(parsed, ensure_ascii=False, indent=2)[:1000])
    except:
        print(r[:500])

    # 2. noteDetail with note_code
    r2 = js(ws, i*10+2, f"""
var r='';
$.ajax({{url:'/ezmaru/pc/note/noteDetail',type:'POST',async:false,
data:{{note_code:'{note_code}'}},
success:function(d){{r=JSON.stringify(d);}},
error:function(e){{r='ERR:'+e.status;}}
}});
r
""")
    print(f"\n[noteDetail] 파일관련 필드:")
    try:
        parsed = json.loads(r2)
        file_keys = {k: v for k, v in parsed.items() if any(x in k.upper() for x in ['FILE','ATTACH','DOWN','URL','PATH'])}
        if file_keys:
            print(json.dumps(file_keys, ensure_ascii=False, indent=2))
        else:
            print("파일 관련 키 없음, 전체 키:", list(parsed.keys()))
    except:
        print(r2[:300])

    if i >= 1:  # 2개만
        break

ws.close()
