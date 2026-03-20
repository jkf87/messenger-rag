# -*- coding: utf-8 -*-
"""noteDetail + fileList 전체 응답 상세 확인"""
import sys, json, urllib.request
from websocket import create_connection

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CDP_URL = "http://127.0.0.1:9000/json"

def js(ws, id_, expr):
    ws.send(json.dumps({"id": id_, "method": "Runtime.evaluate",
                        "params": {"expression": expr}}))
    return json.loads(ws.recv()).get("result", {}).get("result", {}).get("value", "")

pages = json.loads(urllib.request.urlopen(CDP_URL, timeout=3).read())
main  = next(p for p in pages if "main" in p.get("url", ""))
ws    = create_connection(main["webSocketDebuggerUrl"], timeout=10)

# 이전에 200 응답 했던 note_code
note_code = "69bb94395984c313eb000000"

print(f"=== note_code: {note_code} ===")

# 1. noteDetail (note_code 파라미터) 전체 응답
print("\n[1] /ezmaru/pc/note/noteDetail (note_code)")
r = js(ws, 1, f"""
var r='';
$.ajax({{url:'/ezmaru/pc/note/noteDetail',type:'POST',async:false,
data:{{note_code:'{note_code}'}},
success:function(d){{r=JSON.stringify(d);}},
error:function(e){{r='ERR:'+e.status;}}
}});
r
""")
try:
    parsed = json.loads(r)
    print(json.dumps(parsed, ensure_ascii=False, indent=2))
except:
    print(r)

# 2. /ezmaru/pc/file/fileList
print("\n[2] /ezmaru/pc/file/fileList (note_code)")
r2 = js(ws, 2, f"""
var r='';
$.ajax({{url:'/ezmaru/pc/file/fileList',type:'POST',async:false,
data:{{note_code:'{note_code}'}},
success:function(d){{r=JSON.stringify(d);}},
error:function(e){{r='ERR:'+e.status;}}
}});
r2
""")
try:
    parsed = json.loads(r2)
    print(json.dumps(parsed, ensure_ascii=False, indent=2))
except:
    print(r2)

# 3. CDP Network 인터셉트 - 실제 앱에서 쪽지 클릭 시 요청 캡처
import time
ws.send(json.dumps({"id": 99, "method": "Network.enable"}))
ws.recv()

print("\n[3] Network 캡처 시작 - 메신저에서 쪽지를 클릭하세요! (15초 대기)")
start = time.time()
requests_seen = {}

while time.time() - start < 15:
    try:
        ws.settimeout(1)
        msg = json.loads(ws.recv())
        method = msg.get("method", "")

        if method == "Network.requestWillBeSent":
            params = msg["params"]
            req    = params.get("request", {})
            url    = req.get("url", "")
            reqid  = params.get("requestId", "")
            if "ezmaru" in url:
                data = req.get("postData", "")
                requests_seen[reqid] = {"url": url, "data": data, "status": None, "body": None}

        elif method == "Network.responseReceived":
            params = msg["params"]
            url    = params.get("response", {}).get("url", "")
            reqid  = params.get("requestId", "")
            status = params.get("response", {}).get("status", 0)
            if reqid in requests_seen:
                requests_seen[reqid]["status"] = status
                # 응답 바디 가져오기
                ws.send(json.dumps({"id": 200, "method": "Network.getResponseBody",
                                    "params": {"requestId": reqid}}))

        elif msg.get("id") == 200:
            body = msg.get("result", {}).get("body", "")
            # 마지막 요청에 바디 저장
            for k in reversed(list(requests_seen.keys())):
                if requests_seen[k]["body"] is None:
                    requests_seen[k]["body"] = body[:800]
                    break

    except:
        pass

print("\n=== 캡처된 요청 ===")
for reqid, info in requests_seen.items():
    print(f"\nURL: {info['url']}")
    print(f"STATUS: {info['status']}")
    print(f"DATA: {info['data'][:100]}")
    if info['body']:
        print(f"BODY: {info['body'][:400]}")

ws.close()
