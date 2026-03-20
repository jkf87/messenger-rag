# -*- coding: utf-8 -*-
"""window.name 복호화 + 배치 API 호출 탐색"""
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

# 1. window.name 암호화 토큰 복호화
print("=== window.name 토큰 복호화 ===")
r = js(ws, 1, """
var key = pcFuncGetDataEncRawKey();
var wname = window.name;
var afterAt5 = wname.split('@@@@@')[1] || '';
var parts = afterAt5.split(':');
var result = parts.map(function(p, i){
    try {
        var dec = cryptoUtil.decryptAES256WithSHA256Key(p, key);
        return i + ': ' + dec.substring(0,100);
    } catch(e) {
        return i + ': [raw] ' + p.substring(0,40);
    }
});
JSON.stringify(result)
""")
try:
    items = json.loads(r)
    for item in items:
        print(f"  {item}")
except:
    print(r[:500])

# 2. window.name 파싱 - noteDetail이 어떻게 사용하는지 확인
print("\n=== window.name 파싱 구조 ===")
r2 = js(ws, 2, """
var wname = window.name;
var parts = wname.split('@');
JSON.stringify({
    total_at: parts.length,
    part0: parts[0],        // viewnote:CODE
    part1: parts[1],        // :i: (mode?)
    part2: parts[2],        // 크기 정보
    part_before5: parts.slice(0,5),
    after5 : wname.split('@@@@@')[1] ? wname.split('@@@@@')[1].substring(0,80) : 'none'
})
""")
print(r2)

# 3. 암호화 body에 window.name 토큰 포함해서 noteDetail 호출
print("\n=== 인증 토큰 포함 noteDetail 호출 ===")
conn = sqlite3.connect(DB_PATH)
sample_codes = [r[0] for r in conn.execute("SELECT note_code FROM notes WHERE file_cnt > 0 LIMIT 3").fetchall()]
conn.close()

r3 = js(ws, 10, f"""
var key = pcFuncGetDataEncRawKey();
var wname = window.name;
var authPart = wname.split('@@@@@')[1] || '';
var authTokens = authPart.split(':');

// authTokens[0] = session/user token?
var payload = {{
    note_code: '{sample_codes[0]}',
    authToken: authTokens[0] || '',
    token2: authTokens[1] || ''
}};
var body = cryptoUtil.encryptAES256WithSHA256Key(JSON.stringify(payload), key);
var result = '';
$.ajax({{
    url: '/ezmaru/pc/note/noteDetail',
    type: 'POST', async: false,
    data: {{'head[version]':'1.0','head[enctype]':'aes256sha256',
             'head[compress]':'','head[apikey]':'','head[action]':'','body[data]':body}},
    success: function(d) {{
        if(d.body && d.body.data) {{
            result = 'DEC:' + cryptoUtil.decryptAES256WithSHA256Key(d.body.data, key).substring(0,400);
        }} else {{
            result = 'RAW:' + JSON.stringify(d).substring(0,300);
        }}
    }},
    error: function(e) {{ result = 'ERR:'+e.status; }}
}});
result
""")
print(r3[:500])

# 4. 다른 파라미터로 noteDetail 호출 (NTE_CODE, noteCode 등)
print("\n=== 다른 파라미터로 noteDetail 호출 ===")
param_variants = [
    f"{{NTE_CODE:'{sample_codes[0]}'}}",
    f"{{noteCode:'{sample_codes[0]}'}}",
    f"{{code:'{sample_codes[0]}'}}",
    f"{{noteCode:'{sample_codes[0]}', noteType:'R'}}",
    f"{{NTE_CODE:'{sample_codes[0]}', NRU_TYPE:'R'}}",
]
for i, params in enumerate(param_variants):
    r4 = js(ws, 20+i, f"""
var key = pcFuncGetDataEncRawKey();
var body = cryptoUtil.encryptAES256WithSHA256Key(JSON.stringify({params}), key);
var result = '';
$.ajax({{
    url: '/ezmaru/pc/note/noteDetail',
    type: 'POST', async: false,
    data: {{'head[version]':'1.0','head[enctype]':'aes256sha256',
             'head[compress]':'','head[apikey]':'','head[action]':'','body[data]':body}},
    success: function(d) {{
        if(d.body && d.body.data) {{
            result = 'DEC:' + cryptoUtil.decryptAES256WithSHA256Key(d.body.data, key).substring(0,200);
        }} else {{
            result = JSON.stringify(d).substring(0,150);
        }}
    }},
    error: function(e) {{ result = 'ERR:'+e.status; }}
}});
result
""")
    print(f"  {params[:60]} → {r4[:150]}")

# 5. 현재 세션에서 noteDetail이 초기 로드 시 사용한 API 확인
# XHR 인터셉트로 noteDetail 로딩 API 찾기
print("\n=== XHR 인터셉트로 page init API 탐색 ===")
r5 = js(ws, 30, """
// $.ajax를 래핑해서 모든 AJAX 요청 캡처
var captured = [];
var origAjax = $.ajax.bind($);
$.ajax = function(opts) {
    captured.push({url: opts.url, data: JSON.stringify(opts.data||{}).substring(0,100)});
    return origAjax(opts);
};
window._capturedAjax = captured;
'XHR 인터셉트 설정 완료'
""")
print(r5)

# 페이지 init 함수 찾아서 호출
r6 = js(ws, 31, """
// 페이지 DOMContentLoaded 또는 ready 이벤트 재실행
var events = $._data(document, 'events') || {};
JSON.stringify(Object.keys(events))
""")
print(f"document events: {r6}")

ws.close()
