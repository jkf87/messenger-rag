# -*- coding: utf-8 -*-
"""앱 내부 암호화 키로 noteDetail API 배치 호출 탐색"""
import sys, json, urllib.request, sqlite3
from pathlib import Path
from websocket import create_connection

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CDP_URL = "http://127.0.0.1:9000/json"
DB_PATH  = Path(__file__).parent / "messages.db"

def get_pages():
    return json.loads(urllib.request.urlopen(CDP_URL, timeout=3).read())

def js(ws, id_, expr):
    ws.send(json.dumps({"id": id_, "method": "Runtime.evaluate",
                        "params": {"expression": expr}}))
    return json.loads(ws.recv()).get("result", {}).get("result", {}).get("value", "")

pages = get_pages()
note_page = next((p for p in pages if "noteDetail" in p.get("url","") and "webSocketDebuggerUrl" in p), None)
ws = create_connection(note_page["webSocketDebuggerUrl"], timeout=15)

# 1. 암호화 키 획득
print("=== 1. 암호화 키 ===")
key = js(ws, 1, "pcFuncGetDataEncRawKey()")
print(f"key: {key[:40] if key else 'FAIL'}...")

chat_key = js(ws, 2, "pcFuncGetChatEncRawKey()")
print(f"chat_key: {chat_key[:40] if chat_key else 'FAIL'}...")

# 2. cryptoUtil 사용 가능 여부
print("\n=== 2. cryptoUtil ===")
r = js(ws, 3, """
JSON.stringify({
    hasEncrypt: typeof cryptoUtil !== 'undefined' && typeof cryptoUtil.encryptAES256WithSHA256Key === 'function',
    hasCrypto: typeof cryptoUtil !== 'undefined',
    cryptoKeys: typeof cryptoUtil !== 'undefined' ? Object.keys(cryptoUtil).slice(0,10) : []
})
""")
print(r)

# 3. 암호화 테스트
print("\n=== 3. 암호화/복호화 테스트 ===")
conn = sqlite3.connect(DB_PATH)
sample_codes = [r[0] for r in conn.execute("SELECT note_code FROM notes WHERE file_cnt > 0 LIMIT 3").fetchall()]
conn.close()

for note_code in sample_codes[:2]:
    r2 = js(ws, 10, f"""
var key = pcFuncGetDataEncRawKey();
var plainData = JSON.stringify({{note_code: '{note_code}'}});
var encrypted = '';
try {{
    encrypted = cryptoUtil.encryptAES256WithSHA256Key(plainData, key);
}} catch(e) {{
    encrypted = 'err: ' + e.message;
}}
encrypted.substring(0,80)
""")
    print(f"  암호화 ({note_code[:12]}...): {r2}")

# 4. 암호화된 API 호출 테스트
print("\n=== 4. 암호화 API로 noteDetail 호출 ===")
r3 = js(ws, 20, f"""
var key = pcFuncGetDataEncRawKey();
var body = cryptoUtil.encryptAES256WithSHA256Key(JSON.stringify({{note_code:'{sample_codes[0]}'}}), key);
var result = '';
$.ajax({{
    url: '/ezmaru/pc/note/noteDetail',
    type: 'POST', async: false,
    data: {{
        'head[version]': '1.0',
        'head[enctype]': 'aes256sha256',
        'head[compress]': '',
        'head[apikey]': '',
        'head[action]': '',
        'body[data]': body
    }},
    success: function(d) {{
        if(d && d.body && d.body.data) {{
            var dec = cryptoUtil.decryptAES256WithSHA256Key(d.body.data, key);
            result = 'DEC:' + dec.substring(0,400);
        }} else {{
            result = 'RAW:' + JSON.stringify(d).substring(0,300);
        }}
    }},
    error: function(e) {{ result = 'ERR:' + e.status; }}
}});
result
""")
print(r3)

# 5. noteFileList 암호화 API 호출
print("\n=== 5. 암호화 API로 파일 목록 ===")
endpoints = ['noteDetail', 'noteFileList', 'noteView', 'noteFile', 'fileInfo']
for ep in endpoints:
    r4 = js(ws, 30, f"""
var key = pcFuncGetDataEncRawKey();
var body = cryptoUtil.encryptAES256WithSHA256Key(JSON.stringify({{note_code:'{sample_codes[0]}'}}), key);
var result = '';
$.ajax({{
    url: '/ezmaru/pc/note/{ep}',
    type: 'POST', async: false,
    data: {{'head[version]':'1.0','head[enctype]':'aes256sha256','head[compress]':'',
             'head[apikey]':'','head[action]':'','body[data]':body}},
    success: function(d) {{
        if(d && d.body && d.body.data) {{
            var dec = cryptoUtil.decryptAES256WithSHA256Key(d.body.data, key);
            result = 'OK_ENC:' + dec.substring(0,300);
        }} else {{
            result = 'OK_RAW:' + JSON.stringify(d).substring(0,200);
        }}
    }},
    error: function(e) {{ result = 'ERR:'+e.status; }}
}});
result
""")
    print(f"  /note/{ep}: {r4[:200]}")

ws.close()
