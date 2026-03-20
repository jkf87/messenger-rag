// 충북소통메신저 RAG 검색 패널 주입 스크립트
(function() {
    if (document.getElementById('__rag_panel__')) return;

    var style = document.createElement('style');
    style.textContent = `
        #__rag_panel__ {
            position: fixed;
            right: 0;
            top: 0;
            bottom: 0;
            width: 300px;
            background: #fff;
            border-left: 2px solid #4a90d9;
            z-index: 99999;
            display: flex;
            flex-direction: column;
            font-family: 'Malgun Gothic', sans-serif;
            font-size: 13px;
            box-shadow: -3px 0 10px rgba(0,0,0,0.15);
        }
        #__rag_header__ {
            background: #4a90d9;
            color: #fff;
            padding: 10px 12px;
            font-weight: bold;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        #__rag_search_box__ {
            padding: 10px;
            border-bottom: 1px solid #eee;
        }
        #__rag_input__ {
            width: 100%;
            padding: 7px 10px;
            border: 1px solid #ccc;
            border-radius: 4px;
            font-size: 13px;
            box-sizing: border-box;
        }
        #__rag_btn__ {
            margin-top: 6px;
            width: 100%;
            padding: 7px;
            background: #4a90d9;
            color: #fff;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 13px;
        }
        #__rag_btn__:hover { background: #357abd; }
        #__rag_status__ {
            padding: 6px 10px;
            font-size: 11px;
            color: #888;
            border-bottom: 1px solid #eee;
        }
        #__rag_results__ {
            flex: 1;
            overflow-y: auto;
            padding: 8px;
        }
        .rag_result_item {
            background: #f7f9fc;
            border: 1px solid #dde;
            border-radius: 6px;
            padding: 8px 10px;
            margin-bottom: 8px;
            cursor: pointer;
        }
        .rag_result_item:hover { background: #eaf2ff; }
        .rag_result_room {
            font-size: 11px;
            color: #4a90d9;
            font-weight: bold;
            margin-bottom: 3px;
        }
        .rag_result_sender {
            font-size: 11px;
            color: #888;
            margin-bottom: 3px;
        }
        .rag_result_text {
            font-size: 13px;
            color: #333;
            line-height: 1.4;
        }
        .rag_result_date {
            font-size: 11px;
            color: #aaa;
            margin-top: 4px;
            text-align: right;
        }
        .rag_highlight { background: #ffe082; border-radius: 2px; }
        #__rag_toggle__ {
            position: fixed;
            right: 0;
            top: 50%;
            transform: translateY(-50%);
            background: #4a90d9;
            color: #fff;
            border: none;
            border-radius: 4px 0 0 4px;
            padding: 8px 5px;
            cursor: pointer;
            z-index: 100000;
            writing-mode: vertical-rl;
            font-size: 12px;
            font-family: 'Malgun Gothic', sans-serif;
            display: none;
        }
        #__rag_collect_btn__ {
            margin-top: 4px;
            width: 100%;
            padding: 5px;
            background: #5cb85c;
            color: #fff;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
        }
        #__rag_collect_btn__:hover { background: #449d44; }
    `;
    document.head.appendChild(style);

    var panel = document.createElement('div');
    panel.id = '__rag_panel__';
    panel.innerHTML = `
        <div id="__rag_header__">
            <span>💬 메시지 검색</span>
            <button onclick="document.getElementById('__rag_panel__').style.display='none';document.getElementById('__rag_toggle__').style.display='block';"
                style="background:none;border:none;color:#fff;cursor:pointer;font-size:16px;">✕</button>
        </div>
        <div id="__rag_search_box__">
            <input id="__rag_input__" type="text" placeholder="검색어를 입력하세요..." />
            <button id="__rag_btn__" onclick="__ragSearch()">검색</button>
            <button id="__rag_collect_btn__" onclick="__ragCollect()">메시지 수집 시작</button>
        </div>
        <div id="__rag_status__">준비됨 | 서버: <span id="__rag_srv_status__">연결 확인 중...</span></div>
        <div id="__rag_results__"><div style="color:#aaa;text-align:center;margin-top:30px;">수집 후 검색하세요</div></div>
    `;
    document.body.appendChild(panel);

    var toggleBtn = document.createElement('button');
    toggleBtn.id = '__rag_toggle__';
    toggleBtn.textContent = '메시지검색';
    toggleBtn.onclick = function() {
        document.getElementById('__rag_panel__').style.display = 'flex';
        toggleBtn.style.display = 'none';
    };
    document.body.appendChild(toggleBtn);

    // 엔터키 검색
    document.getElementById('__rag_input__').addEventListener('keydown', function(e) {
        if (e.key === 'Enter') __ragSearch();
    });

    var RAG_SERVER = 'http://127.0.0.1:8765';

    // 서버 상태 확인
    function checkServer() {
        fetch(RAG_SERVER + '/status')
            .then(r => r.json())
            .then(d => {
                document.getElementById('__rag_srv_status__').textContent =
                    '연결됨 (메시지 ' + d.count + '건)';
            })
            .catch(() => {
                document.getElementById('__rag_srv_status__').textContent = '서버 미실행';
            });
    }
    checkServer();
    setInterval(checkServer, 10000);

    // 메시지 수집
    window.__ragCollect = function() {
        var btn = document.getElementById('__rag_collect_btn__');
        btn.disabled = true;
        btn.textContent = '수집 중...';
        document.getElementById('__rag_status__').textContent = '채팅방 목록 가져오는 중...';

        $.ajax({
            url: '/ezmaru/pc/chatroom/chatroomlist',
            type: 'POST',
            success: function(roomData) {
                var rooms = roomData.LIST || [];
                document.getElementById('__rag_status__').textContent =
                    '채팅방 ' + rooms.length + '개 발견, 메시지 수집 중...';

                var allMessages = [];
                var pending = rooms.length;

                if (pending === 0) {
                    btn.disabled = false;
                    btn.textContent = '메시지 수집 시작';
                    return;
                }

                rooms.forEach(function(room) {
                    collectRoomMessages(room, 1, [], function(msgs) {
                        allMessages = allMessages.concat(msgs);
                        pending--;
                        document.getElementById('__rag_status__').textContent =
                            '수집 중... ' + (rooms.length - pending) + '/' + rooms.length;
                        if (pending === 0) {
                            sendToServer(allMessages, function() {
                                btn.disabled = false;
                                btn.textContent = '메시지 수집 시작';
                                checkServer();
                            });
                        }
                    });
                });
            },
            error: function() {
                document.getElementById('__rag_status__').textContent = '채팅방 목록 오류';
                btn.disabled = false;
                btn.textContent = '메시지 수집 시작';
            }
        });
    };

    // 채팅방 메시지 수집 (페이지 단위)
    function collectRoomMessages(room, page, accumulated, callback) {
        var apiUrls = [
            '/ezmaru/pc/chatroom/messagelist',
            '/ezmaru/pc/message/list',
            '/ezmaru/pc/chatroom/msglist'
        ];
        var urlIdx = 0;

        function tryNext() {
            if (urlIdx >= apiUrls.length) { callback(accumulated); return; }
            $.ajax({
                url: apiUrls[urlIdx],
                type: 'POST',
                data: { NCS_SCODE: room.NCS_SCODE, page: page, pageSize: 100 },
                success: function(data) {
                    var msgs = (data.LIST || data.list || data.messages || []).map(function(m) {
                        return {
                            room_id: room.NCS_SCODE,
                            room_name: room.NCS_TITLE,
                            sender: m.NUR_NIC || m.sender || m.NUR_NAME || '',
                            text: m.NCM_CONTENT || m.content || m.message || m.text || '',
                            date: m.NCM_DATE || m.date || m.created_at || ''
                        };
                    }).filter(function(m) { return m.text; });

                    accumulated = accumulated.concat(msgs);
                    // 다음 페이지 있으면 계속
                    var total = data.TOTAL || data.total || 0;
                    if (total > page * 100) {
                        collectRoomMessages(room, page + 1, accumulated, callback);
                    } else {
                        callback(accumulated);
                    }
                },
                error: function() { urlIdx++; tryNext(); }
            });
        }
        tryNext();
    }

    // 수집한 메시지 서버로 전송
    function sendToServer(messages, callback) {
        fetch(RAG_SERVER + '/collect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ messages: messages })
        })
        .then(r => r.json())
        .then(d => {
            document.getElementById('__rag_status__').textContent =
                '수집 완료: ' + d.saved + '건 저장';
            if (callback) callback();
        })
        .catch(e => {
            document.getElementById('__rag_status__').textContent = '서버 전송 오류';
            if (callback) callback();
        });
    }

    // 검색
    window.__ragSearch = function() {
        var q = document.getElementById('__rag_input__').value.trim();
        if (!q) return;

        var resultsDiv = document.getElementById('__rag_results__');
        resultsDiv.innerHTML = '<div style="color:#aaa;text-align:center;margin-top:30px;">검색 중...</div>';

        fetch(RAG_SERVER + '/search?q=' + encodeURIComponent(q))
            .then(r => r.json())
            .then(function(data) {
                if (!data.results || data.results.length === 0) {
                    resultsDiv.innerHTML = '<div style="color:#aaa;text-align:center;margin-top:30px;">결과 없음</div>';
                    return;
                }
                resultsDiv.innerHTML = data.results.map(function(item) {
                    var highlighted = item.text.replace(
                        new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'), 'gi'),
                        '<span class="rag_highlight">$&</span>'
                    );
                    return `<div class="rag_result_item">
                        <div class="rag_result_room">${item.room_name || item.room_id}</div>
                        <div class="rag_result_sender">${item.sender}</div>
                        <div class="rag_result_text">${highlighted}</div>
                        <div class="rag_result_date">${item.date}</div>
                    </div>`;
                }).join('');
            })
            .catch(function() {
                resultsDiv.innerHTML = '<div style="color:#e44;text-align:center;margin-top:30px;">서버 연결 실패<br>main.py를 실행해주세요</div>';
            });
    };

})();
