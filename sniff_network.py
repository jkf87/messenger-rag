# -*- coding: utf-8 -*-
"""CDP 네트워크 스니퍼 - 쪽지/첨부 관련 요청 캡처"""
import sys, json, urllib.request, time
from websocket import create_connection

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CDP_URL = "http://127.0.0.1:9000/json"

pages = json.loads(urllib.request.urlopen(CDP_URL, timeout=3).read())
main  = next(p for p in pages if "main" in p.get("url", ""))
ws    = create_connection(main["webSocketDebuggerUrl"], timeout=30)

ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
ws.recv()

print("=" * 60)
print("네트워크 스니퍼 시작")
print("메신저에서 쪽지를 열고, 첨부파일을 클릭해보세요!")
print("Ctrl+C 로 종료")
print("=" * 60)

body_queue = {}  # reqId -> info

try:
    while True:
        ws.settimeout(60)
        raw = ws.recv()
        msg = json.loads(raw)
        method = msg.get("method", "")

        if method == "Network.requestWillBeSent":
            p   = msg["params"]
            req = p.get("request", {})
            url = req.get("url", "")
            rid = p.get("requestId", "")
            if "ezmaru" in url or "stmsg" in url:
                data = req.get("postData", "")
                body_queue[rid] = {"url": url, "data": data}
                print(f"\n→ REQ  {url}")
                if data:
                    print(f"   DATA: {data[:150]}")

        elif method == "Network.responseReceived":
            p      = msg["params"]
            rid    = p.get("requestId", "")
            status = p.get("response", {}).get("status", "")
            url    = p.get("response", {}).get("url", "")
            if rid in body_queue:
                body_queue[rid]["status"] = status
                print(f"← RESP [{status}] {url}")
                # 응답 바디 요청
                ws.send(json.dumps({
                    "id": int(time.time() * 1000) % 100000,
                    "method": "Network.getResponseBody",
                    "params": {"requestId": rid}
                }))

        elif "result" in msg and "body" in msg.get("result", {}):
            body = msg["result"]["body"]
            if body:
                print(f"   BODY: {body[:600]}")

except KeyboardInterrupt:
    print("\n\n종료")
finally:
    ws.close()
