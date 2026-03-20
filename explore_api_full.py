# -*- coding: utf-8 -*-
"""noteDetail API + noteList API 전체 응답에서 파일 정보 탐색"""
import sys, json, urllib.request, sqlite3, base64
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

# DB에서 파일 있는 쪽지
conn = sqlite3.connect(DB_PATH)
file_notes = conn.execute("SELECT note_code, title, file_cnt FROM notes WHERE file_cnt > 0 LIMIT 5").fetchall()
conn.close()

# 1. noteList API 전체 응답 (파일 있는 쪽지 찾아서 전체 필드 확인)
print("=== noteList API 전체 필드 (파일있는 쪽지) ===")
target_codes = [r[0] for r in file_notes[:3]]
r = js(ws, 1, f"""
var r='';
$.ajax({{
    url:'/ezmaru/pc/note/noteList',
    type:'POST', async:false,
    data:{{pageSize:1000, pageNo:1, noteType:'receive'}},
    success:function(d){{
        var codes = {json.dumps(target_codes)};
        var found = d.LIST.filter(function(x){{ return codes.indexOf(x.NTE_CODE) >= 0; }});
        r = JSON.stringify(found);
    }},
    error:function(e){{ r='ERR:'+e.status; }}
}});
r
""")
try:
    items = json.loads(r)
    for item in items[:2]:
        print(json.dumps(item, ensure_ascii=False, indent=2)[:2000])
        print("---")
except:
    print(r[:500])

# 2. noteDetail API 전체 응답 (파일 있는 쪽지)
print("\n=== noteDetail API 전체 응답 ===")
for note_code, title, file_cnt in file_notes[:3]:
    print(f"\n쪽지: {title[:40]} (files={file_cnt})")
    r2 = js(ws, 2, f"""
var r='';
$.ajax({{
    url:'/ezmaru/pc/note/noteDetail',
    type:'POST', async:false,
    data:{{note_code:'{note_code}'}},
    success:function(d){{r=JSON.stringify(d);}},
    error:function(e){{r='ERR:'+e.status;}}
}});
r
""")
    try:
        parsed = json.loads(r2)
        if isinstance(parsed, dict):
            # 파일 관련 키 찾기
            file_keys = {k: v for k, v in parsed.items() if any(x in k.upper() for x in ['FILE','ATTACH','DOWN','UPLOAD'])}
            if file_keys:
                print("  파일 관련 필드:", json.dumps(file_keys, ensure_ascii=False))
            else:
                print("  전체 키:", list(parsed.keys()))
                print("  전체:", json.dumps(parsed, ensure_ascii=False)[:500])
    except:
        print(f"  결과: {r2[:300]}")

# 3. /ezmaru/pc/note/noteView 시도 (note_code 파라미터)
print("\n=== /ezmaru/pc/note/noteView API ===")
for note_code, title, file_cnt in file_notes[:2]:
    print(f"\n쪽지: {title[:30]}")
    for endpoint in ['noteView','noteOpen','noteRead','noteFileInfo','noteFileList2']:
        r3 = js(ws, 3, f"""
var r='';
$.ajax({{url:'/ezmaru/pc/note/{endpoint}',type:'POST',async:false,
data:{{note_code:'{note_code}'}},
success:function(d){{r='OK:'+JSON.stringify(d).substring(0,200);}},
error:function(e){{r='ERR:'+e.status;}}
}});
r
""")
        if r3.startswith("OK:"):
            print(f"  ✓ {endpoint}: {r3[3:300]}")

# 4. 현재 열려있는 쪽지 DOM에서 직접 파일 URL 추출 (정확한 selector 찾기)
print("\n=== 현재 DOM 상세 분석 ===")
r4 = js(ws, 4, """
// hidden input 전체 목록
var inputs = Array.from(document.querySelectorAll('input[type=hidden]')).map(function(el){
    return {name: el.name || el.id, value: (el.value||'').substring(0,50)};
});
// fileurl 속성 있는 모든 요소
var fileEls = Array.from(document.querySelectorAll('[fileurl]')).map(function(el){
    return {
        tag: el.tagName,
        cls: el.className.substring(0,40),
        fileurl: (el.getAttribute('fileurl')||'').substring(0,100),
        oriname: el.getAttribute('oriname')
    };
});
JSON.stringify({inputs: inputs.slice(0,20), fileEls: fileEls})
""")
try:
    data = json.loads(r4)
    print("Hidden inputs:", json.dumps(data['inputs'], ensure_ascii=False))
    print("\nfileurl 요소들:")
    for el in data['fileEls']:
        try:
            fname = base64.b64decode(el['oriname']).decode('utf-8') if el.get('oriname') else ''
        except:
            fname = ''
        print(f"  [{el['tag']}] {el['cls']} | {fname} | {el['fileurl']}")
except:
    print(r4[:500])

ws.close()
