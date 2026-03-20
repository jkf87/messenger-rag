# AGENTS.md — LLM/AI 에이전트용 코드베이스 가이드

이 문서는 LLM 코딩 에이전트가 이 레포지토리를 빠르게 파악하고 작업할 수 있도록 작성된 가이드입니다.

---

## 프로젝트 개요

**목적:** 충북소통메신저(웹 기반 직장 메신저)의 쪽지·채팅 데이터를 로컬 수집 후,
Hybrid RAG + Graph RAG로 시맨틱 검색·시각화하는 Windows 데스크톱 앱.

**핵심 제약:**
- LLM 추론 없음 — 모든 검색·그래프 생성은 코드베이스 기반
- CPU 전용 (GPU 불필요)
- Windows 전용 (tkinter GUI, CDP WebSocket)
- 학교 네트워크 SSL 프록시 우회 필요 (httpx/requests verify=False 패치)

---

## 아키텍처

```
[Chrome 메신저]
      │ CDP WebSocket (port 9000)
      ▼
[backup_notes.py]       → messages.db (SQLite)
[fetch_full_content.py] → messages.db (쪽지 본문 갱신)
[batch_download.py]     → attachments/ (첨부파일)
      │
      ▼
[build_index.py]        → embed_index.pkl
  └─ multilingual-e5-small 임베딩 (passage: prefix)
      │
      ▼
[search_app_win.py]  ← 메인 GUI
  ├─ [local_rag.py]      : 시맨틱 검색 (코사인 유사도)
  ├─ [graph_rag.py]      : Graph RAG 추론 체인 데이터 생성
  └─ [graph_canvas.py]   : tkinter Canvas 그래프 위젯
```

---

## 핵심 파일별 역할

### `search_app_win.py`
- tkinter 기반 메인 앱 (App 클래스, tk.Tk 상속)
- 탭: 채팅 메시지 / 쪽지
- 검색 모드: 키워드(SQLite LIKE) / 로컬RAG / AI의미검색(Anthropic API, 옵션)
- 우측 패널: `GraphWidget` 임베드, 선택 쪽지 hop 체인 자동 표시
- 수집 버튼 4개: subprocess로 스크립트 실행, 결과를 상태바에 스트리밍
- RAG 모델: 앱 시작 시 백그라운드 스레드에서 preload (`_preload_rag`)

### `local_rag.py`
- `_load()`: embed_index.pkl 로드 + SentenceTransformer 모델 로드 (lazy)
- `rag_search_notes(q, note_type, sender, top_k)`: 쪽지 시맨틱 검색
- `rag_search_messages(q, room, sender, top_k)`: 메시지 시맨틱 검색
- `_last_note_scores: dict`: 마지막 검색의 note_code→유사도 점수 저장 (graph_rag 참조용)
- **중요:** notes 인덱스는 8컬럼, DB는 9컬럼(read_yn 포함) → `r[:7] + ('Y',) + r[7:]`로 보정

### `graph_rag.py`
- `get_hop_graph_data(note_code, query, sim_score)`: 단일 쪽지 hop 체인 → GraphWidget용 dict
  - Hop 0: 쿼리 노드
  - Hop 1: 매칭 쪽지 노드
  - Hop 2: 발신자(person) + 키워드(keyword) 노드
  - Hop 3: 연결 쪽지(related) 노드
- `get_full_graph_data(note_rows, query, scores)`: 검색 결과 전체 → 방사형 그래프용 dict
  - 쿼리 중심, 매칭 쪽지 방사형, 같은 발신자 연결
- `open_hop_graph(...)`: pyvis HTML 생성 후 브라우저 열기 (레거시, 현재 미사용)

#### 그래프 데이터 구조
```python
{
  "nodes": [
    {"id": str, "type": "query|note|person|keyword|related",
     "label": str, "detail": str}
  ],
  "edges": [
    {"from": str, "to": str,
     "type": "similarity|person|keyword|person_rel|keyword_rel",
     "label": str}
  ]
}
```

### `graph_canvas.py`
- `GraphWidget(tk.Frame)`: 임베드 가능한 그래프 위젯
- `set_graph(data, layout="auto")`: 그래프 데이터 설정 및 렌더링
  - `layout="hierarchical"`: 레이어별 상하 배치 (hop chain용)
  - `layout="radial"`: 중앙→방사형 (전체 보기용)
  - `layout="auto"`: note 노드 5개 이상이면 radial, 미만이면 hierarchical
- 노드 드래그: `<B1-Motion>` 이벤트로 위치 조정 후 redraw
- hover 툴팁: `node["detail"]` 텍스트를 `tk.Toplevel`로 표시
- `<Configure>` 이벤트: 패널 리사이즈 시 자동 레이아웃 재계산

### `build_index.py`
- SSL 패치 (httpx + ssl) → sentence-transformers 임포트
- `notes`: `SELECT note_code, note_type, sender, receiver, title, content, note_date, file_cnt`
- 임베딩 텍스트: `f"passage: {title} {content[:300]}"`
- `messages`: `SELECT room_code, room_name, sender, content, msg_time, msg_date`
- 임베딩 텍스트: `f"passage: {room_name} {sender} {content[:200]}"`
- 저장: `pickle.dump({"notes": [...], "note_embs": np.array, "msgs": [...], "msg_embs": np.array, "model": MODEL_NAME})`

---

## 임베딩 모델 상세

| 항목 | 내용 |
|---|---|
| 모델 | `intfloat/multilingual-e5-small` |
| 크기 | 117MB |
| 차원 | 384 |
| 언어 | 다국어 (한국어 포함) |
| prefix 규칙 | 문서: `"passage: {text}"`, 쿼리: `"query: {text}"` |
| 유사도 | 코사인 (정규화된 벡터의 내적 = `embs @ qv`) |
| 연산 | CPU 전용, batch_size=32 |
| 소요 시간 | 약 1,000건 65초 (CPU) |

---

## 데이터베이스 스키마

### `notes` 테이블
```sql
CREATE TABLE notes (
    note_code  TEXT PRIMARY KEY,
    note_type  TEXT,        -- 'receive' | 'send'
    sender     TEXT,
    receiver   TEXT,
    title      TEXT,
    content    TEXT,        -- 초기 100자 → fetch_full_content로 갱신
    note_date  TEXT,        -- '20260319151418891' 형식
    read_yn    TEXT,        -- 'Y' | 'N'
    file_cnt   INTEGER
)
```

### `messages` 테이블
```sql
CREATE TABLE messages (
    room_code  TEXT,
    room_name  TEXT,
    sender     TEXT,
    content    TEXT,
    msg_time   TEXT,
    msg_date   TEXT
)
```

---

## Hybrid RAG 검색 방식

```
사용자 쿼리
    │
    ├─ [키워드 검색] SQLite: WHERE title LIKE '%q%' OR content LIKE '%q%'
    │                       → 정확한 단어 매칭
    │
    └─ [시맨틱 검색] query 벡터 = encode("query: {q}")
                    scores = note_embs @ query_vec  (코사인 유사도)
                    top_k 결과 반환
                    → 맞춤법 오류·동의어·문맥 검색 가능
```

키워드와 시맨틱 중 하나를 선택 (로컬RAG 체크박스로 전환).
두 결과를 합산하는 RRF(Reciprocal Rank Fusion) 방식은 미구현.

---

## CDP(Chrome DevTools Protocol) 수집 방식

```python
# 연결
pages = json.loads(urllib.request.urlopen("http://127.0.0.1:9000/json").read())
ws_url = next(p["webSocketDebuggerUrl"] for p in pages if "noteDetail" in p["url"])
ws = create_connection(ws_url)

# JS 실행
ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": "..."}}))
result = json.loads(ws.recv())["result"]["result"]["value"]

# 핵심: $.ajax 직접 호출 (EZAjax 암호화 불필요)
# /pc/note/noteList  → 쪽지 목록 (content 100자 제한)
# /pc/note/noteDetail → 쪽지 전체 내용 (nteCode 파라미터)
```

---

## 주요 패턴 / 주의사항

1. **SSL 우회**: `local_rag.py`, `build_index.py` 상단에 httpx 패치 필수
   ```python
   import httpx
   _orig = httpx.Client.__init__
   def _p(self, *a, **kw): kw.setdefault("verify", False); _orig(self, *a, **kw)
   httpx.Client.__init__ = _p
   ```

2. **note 컬럼 수 불일치**: 인덱스(8컬럼) vs DB(9컬럼, read_yn 포함)
   ```python
   results = [r[:7] + ('Y',) + r[7:] for r in results]
   ```

3. **tkinter 스레드 안전**: 백그라운드 스레드에서 GUI 업데이트 시 반드시 `self.after(0, lambda: ...)`

4. **날짜 형식**: `20260319151418891` → `fmt_note_date()` 함수로 `2026-03-19 15:14` 변환

5. **경로**: 모든 파일 경로는 `Path(__file__).parent` 기준 상대 경로 사용

---

## 확장 포인트

- **RRF 하이브리드**: 키워드 + 시맨틱 점수를 `1/(rank+60)` 공식으로 합산
- **청킹**: 긴 쪽지 내용을 512토큰 단위로 분할 임베딩
- **재랭킹**: cross-encoder 모델로 top-k 재정렬
- **Graph DB 연동**: 현재 in-memory 그래프를 Neo4j로 이관
- **스트리밍 검색**: 실시간 입력 중 결과 갱신 (debounce 300ms)
