# -*- coding: utf-8 -*-
"""CDP 네트워크 인터셉트로 쪽지 첨부파일 API 탐색"""
import sys, json, sqlite3, urllib.request, time
from pathlib import Path
from websocket import create_connection

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = Path(__file__).parent / "messages.db"
CDP_URL  = "http://127.0.0.1:9000/json"

def js(ws, id_, expr):
    ws.send(json.dumps({"id": id_, "method": "Runtime.evaluate",
                         "params": {"expression": expr, "awaitPromise": False}}))
    return json.loads(ws.recv()).get("result", {}).get("result", {}).get("value", "")

pages = json.loads(urllib.request.urlopen(CDP_URL, timeout=3).read())
main  = next(p for p in pages if "main" in p.get("url", ""))
ws    = create_connection(main["webSocketDebuggerUrl"], timeout=15)

# Network 이벤트 활성화
ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
ws.recv()
print("[네트워크 모니터 ON]")

# noteList 전체 응답에서 파일 관련 필드 확인
print("\n=== noteList 원본 첫 1건 전체 필드 ===")
result = js(ws, 10, """
var r='';
$.ajax({
    url:'/ezmaru/pc/note/noteList',
    type:'POST', async:false,
    data:{pageSize:1, pageNo:1, noteType:'receive'},
    success:function(d){ r=JSON.stringify(d.LIST[0]); },
    error:function(e){ r='ERR:'+e.status; }
});
r
""")
print(result)

# 파일 있는 쪽지의 전체 필드
conn = sqlite3.connect(DB_PATH)
rows = conn.execute("SELECT note_code FROM notes WHERE file_cnt > 0 LIMIT 3").fetchall()
conn.close()
note_codes = [r[0] for r in rows]

print(f"\n=== 파일 있는 쪽지 noteList에서 찾기 ===")
result = js(ws, 20, f"""
var r='';
$.ajax({{
    url:'/ezmaru/pc/note/noteList',
    type:'POST', async:false,
    data:{{pageSize:1000, pageNo:1, noteType:'receive'}},
    success:function(d){{
        var found = d.LIST.filter(function(x){{ return x.NTE_CODE==='{note_codes[0]}'; }});
        r = found.length > 0 ? JSON.stringify(found[0]) : 'NOT_FOUND';
    }},
    error:function(e){{ r='ERR:'+e.status; }}
}});
r
""")
print(result)

# 다양한 파라미터로 noteDetail 재시도
print("\n=== noteDetail 파라미터 변형 시도 ===")
params_list = [
    f"{{noteCode:'{note_codes[0]}'}}",
    f"{{NTE_CODE:'{note_codes[0]}'}}",
    f"{{note_code:'{note_codes[0]}'}}",
    f"{{noteCode:'{note_codes[0]}', noteType:'receive'}}",
]
for i, param in enumerate(params_list):
    r = js(ws, 30+i, f"""
var r='';
$.ajax({{url:'/ezmaru/pc/note/noteDetail',type:'POST',async:false,
data:{param},
success:function(d){{r='OK:'+JSON.stringify(d);}},
error:function(e){{r='ERR:'+e.status;}}
}});
r
""")
    print(f"  {param[:50]} → {r[:200]}")

# 다른 URL 패턴 시도
print("\n=== 다른 URL 패턴 ===")
urls = [
    ("/ezmaru/pc/note/noteRead",   f"{{noteCode:'{note_codes[0]}'}}"),
    ("/ezmaru/pc/note/noteInfo",   f"{{noteCode:'{note_codes[0]}'}}"),
    ("/ezmaru/file/fileList",      f"{{noteCode:'{note_codes[0]}'}}"),
    ("/ezmaru/pc/file/fileList",   f"{{noteCode:'{note_codes[0]}'}}"),
    ("/ezmaru/pc/note/noteOpen",   f"{{noteCode:'{note_codes[0]}'}}"),
]
for i, (url, param) in enumerate(urls):
    r = js(ws, 40+i, f"""
var r='';
$.ajax({{url:'{url}',type:'POST',async:false,data:{param},
success:function(d){{r='OK:'+JSON.stringify(d);}},
error:function(e){{r='ERR:'+e.status;}}
}});
r
""")
    print(f"  {url} → {r[:200]}")

print("\n=== 쪽지 탭 클릭 후 네트워크 요청 캡처 (10초) ===")
print("쪽지 탭을 클릭하고 쪽지 하나를 클릭해보세요...")

# 네트워크 요청 캡처
js(ws, 99, 'document.querySelector("a.note") && document.querySelector("a.note").click()')
start = time.time()
captured = []
while time.time() - start < 10:
    try:
        ws.settimeout(1)
        msg = json.loads(ws.recv())
        method = msg.get("method", "")
        if method == "Network.requestWillBeSent":
            req = msg["params"].get("request", {})
            url = req.get("url", "")
            if "ezmaru" in url:
                post_data = req.get("postData", "")
                captured.append(f"  URL: {url}\n  DATA: {post_data[:100]}")
        elif method == "Network.responseReceived":
            resp = msg["params"].get("response", {})
            url  = resp.get("url", "")
            if "ezmaru" in url and url not in [c.split('\n')[0] for c in captured]:
                captured.append(f"  RESP: {url} [{resp.get('status')}]")
    except:
        pass

for c in captured:
    print(c)
if not captured:
    print("(캡처된 요청 없음 - 쪽지를 직접 클릭해보세요)")

ws.close()
