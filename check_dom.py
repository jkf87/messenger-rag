import sys, json, urllib.request
from websocket import create_connection
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

pages = json.loads(urllib.request.urlopen('http://127.0.0.1:9000/json', timeout=3).read())
ws_url = next(p['webSocketDebuggerUrl'] for p in pages if 'noteDetail' in p.get('url','') and 'webSocketDebuggerUrl' in p)
ws = create_connection(ws_url, timeout=15)

def js(id_, expr):
    ws.send(json.dumps({'id': id_, 'method': 'Runtime.evaluate', 'params': {'expression': expr}}))
    return json.loads(ws.recv()).get('result',{}).get('result',{}).get('value','')

r = js(1, """
var el1 = document.querySelector('.detailContent');
var el2 = document.querySelector('.widget-main.padding-6');
var el3 = document.querySelector('.detailContentsArea .widget-main');
var code = document.querySelector('input[name=code]');
JSON.stringify({
    detailContent: el1 ? el1.innerText.substring(0,200) : null,
    widget_main: el2 ? el2.innerText.substring(0,200) : null,
    contentsArea: el3 ? el3.innerText.substring(0,200) : null,
    note_code: code ? code.value : null
})
""")
print(r)
ws.close()
