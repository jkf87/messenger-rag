# -*- coding: utf-8 -*-
"""
Graph RAG - pyvis 기반 인터랙티브 그래프 시각화
- 쿼리 → 쪽지 → 발신자/키워드 → 연결 쪽지 (hop 추론)
- pyvis HTML 생성 → 브라우저에서 Neo4j 스타일 그래프 표시
"""
import sqlite3, re, tempfile, webbrowser, os
from pathlib import Path
from pyvis.network import Network

DB_PATH = Path(__file__).parent / "messages.db"

STOPWORDS = set(
    "있는 있고 있습 합니다 하는 하여 에서 으로 에게 이고 이며 이다 위해 통해 대한 "
    "관련 사항 경우 때문 이후 이전 동안 이상 이하 기준 바랍 바람 부탁 안내 공지 "
    "드립 드리 해서 하고 하며 그리고 그러나 하지만 또한 따라서 그런데 이번 해당 "
    "문의 답변 확인 처리 요청 진행 완료 예정 계획 관련하여 드립니다".split()
)

# 마지막으로 열린 그래프 HTML 경로 (재사용)
_last_html: Path = None


def extract_keywords(text):
    if not text:
        return []
    words = re.findall(r'[가-힣]{2,}|[a-zA-Z0-9]{3,}', text)
    return [w for w in words if w not in STOPWORDS]


def _fmt_date(d):
    if d and len(d) >= 8:
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return d or ""


def get_hop_graph_data(note_code: str, query: str, sim_score: float = None) -> dict:
    """
    Graph RAG 추론 체인을 구조화된 dict로 반환 (GraphWidget.set_graph()용).
    {'nodes': [...], 'edges': [...]}
    """
    conn = sqlite3.connect(DB_PATH)
    note = conn.execute(
        "SELECT note_code, note_type, sender, receiver, title, content, note_date "
        "FROM notes WHERE note_code=?", (note_code,)
    ).fetchone()
    if not note:
        conn.close()
        return {"nodes": [], "edges": []}

    _, ntype, sender, receiver, title, content, note_date = note
    full_text = (title or '') + ' ' + (content or '')

    q_kws  = extract_keywords(query)
    n_set  = set(extract_keywords(full_text))
    overlap = []
    for qk in q_kws:
        for nk in n_set:
            if qk in nk or nk in qk:
                overlap.append((qk, nk))
                break

    sender_notes = conn.execute(
        "SELECT note_code, title, note_date, receiver FROM notes "
        "WHERE sender=? AND note_code!=? ORDER BY note_date DESC LIMIT 4",
        (sender, note_code)
    ).fetchall()

    kw_related = {}
    for _, nk in overlap[:3]:
        rows = conn.execute(
            "SELECT note_code, title, note_date, sender FROM notes "
            "WHERE (title LIKE ? OR content LIKE ?) AND note_code!=? LIMIT 3",
            (f'%{nk}%', f'%{nk}%', note_code)
        ).fetchall()
        if rows:
            kw_related[nk] = rows
    conn.close()

    nodes, edges = [], []

    # Hop 0 - 쿼리
    q_label = query if len(query) <= 18 else query[:17] + "…"
    score_str = f"유사도 {sim_score:.3f}" if sim_score is not None else ""
    nodes.append({"id": "query", "type": "query",
                  "label": f"🔍 {q_label}",
                  "detail": f"검색 쿼리: {query}\n{score_str}"})

    # Hop 1 - 매칭 쪽지
    note_id   = f"note_{note_code}"
    type_lbl  = "받은" if ntype == "receive" else "보낸"
    n_title   = (title or "(제목없음)")[:22]
    date_str  = _fmt_date(note_date)
    nodes.append({"id": note_id, "type": "note",
                  "label": f"📨 {n_title}\n{date_str}",
                  "detail": (f"[{type_lbl}쪽지] {date_str}\n"
                             f"보낸이: {sender}\n받는이: {receiver}\n"
                             f"제목: {title or ''}\n"
                             f"내용: {(content or '')[:200]}{'…' if len(content or '') > 200 else ''}")})
    edges.append({"from": "query", "to": note_id,
                  "type": "similarity",
                  "label": f"{sim_score:.3f}" if sim_score else "매칭"})

    # Hop 2 - 발신자
    person_id = f"person_{sender}"
    nodes.append({"id": person_id, "type": "person",
                  "label": (sender or '')[:10],
                  "detail": f"발신자: {sender}\n관련 쪽지 {len(sender_notes)}건"})
    edges.append({"from": note_id, "to": person_id, "type": "person", "label": "발신자"})

    # Hop 2 - 키워드
    added_kw = set()
    for qk, nk in overlap[:4]:
        kw_id = f"kw_{nk}"
        if kw_id not in added_kw:
            nodes.append({"id": kw_id, "type": "keyword",
                          "label": f"🔑 {nk}",
                          "detail": f"공통 키워드\n쿼리: \"{qk}\"\n본문: \"{nk}\""})
            edges.append({"from": note_id, "to": kw_id, "type": "keyword", "label": "키워드"})
            added_kw.add(kw_id)

    # Hop 3 - 발신자 연결 쪽지
    for rel_nc, rel_t, rel_d, rel_r in sender_notes[:3]:
        rid = f"rel_p_{rel_nc}"
        rt  = (rel_t or "(제목없음)")[:20]
        nodes.append({"id": rid, "type": "related",
                      "label": f"📄 {rt}\n{_fmt_date(rel_d)}",
                      "detail": f"발신자 연결 쪽지\n날짜: {_fmt_date(rel_d)}\n제목: {rel_t or ''}\n→ {rel_r}"})
        edges.append({"from": person_id, "to": rid, "type": "person_rel", "label": ""})

    # Hop 3 - 키워드 연결 쪽지
    for nk, kw_notes in kw_related.items():
        kw_id = f"kw_{nk}"
        for rel_nc, rel_t, rel_d, rel_s in kw_notes[:2]:
            rid = f"rel_k_{nk[:4]}_{rel_nc}"
            if any(n["id"] == rid for n in nodes):
                continue
            rt = (rel_t or "(제목없음)")[:20]
            nodes.append({"id": rid, "type": "related",
                          "label": f"📄 {rt}\n{_fmt_date(rel_d)}",
                          "detail": f"키워드 \"{nk}\" 연결\n날짜: {_fmt_date(rel_d)}\n제목: {rel_t or ''}\n발신자: {rel_s}"})
            if kw_id in added_kw:
                edges.append({"from": kw_id, "to": rid, "type": "keyword_rel", "label": ""})

    return {"nodes": nodes, "edges": edges}


def get_full_graph_data(note_rows: list, query: str, scores: dict = None) -> dict:
    """
    검색 결과 쪽지들만 한 화면에 표시.
    - 쿼리 노드 → 각 쪽지 노드 (유사도 엣지)
    - 같은 발신자끼리 점선 엣지로 연결
    """
    if not note_rows:
        return {"nodes": [], "edges": []}

    scores = scores or {}
    nodes, edges = [], []

    # 쿼리 노드
    q_label = query if len(query) <= 18 else query[:17] + "…"
    nodes.append({"id": "query", "type": "query",
                  "label": f"🔍 {q_label}",
                  "detail": f"검색 쿼리: {query}\n결과 {len(note_rows)}건"})

    # 쪽지 노드 + 쿼리 엣지
    sender_to_notes = {}  # sender → [nid, ...]
    for r in note_rows[:30]:
        note_code = r[0]
        ntype     = r[1]
        sender    = r[2]
        title     = r[4] or ""
        note_date = r[6]

        nid       = f"note_{note_code}"
        type_lbl  = "받은" if ntype == "receive" else "보낸"
        n_title   = title[:22]
        date_str  = _fmt_date(note_date)
        score     = scores.get(note_code)
        score_str = f"{score:.3f}" if score else "매칭"

        nodes.append({"id": nid, "type": "note",
                      "label": f"📨 {n_title}\n{date_str}",
                      "detail": (f"[{type_lbl}쪽지] {date_str}\n"
                                 f"보낸이: {sender}\n제목: {title}")})
        edges.append({"from": "query", "to": nid,
                      "type": "similarity", "label": score_str})

        sender_to_notes.setdefault(sender, []).append(nid)

    # 같은 발신자 쪽지끼리 점선 연결
    for sender, nids in sender_to_notes.items():
        if len(nids) > 1:
            for i in range(len(nids) - 1):
                edges.append({"from": nids[i], "to": nids[i + 1],
                               "type": "person", "label": sender[:6]})

    return {"nodes": nodes, "edges": edges}


def open_hop_graph(note_code: str, query: str, sim_score: float = None):
    """
    Graph RAG 추론 체인을 pyvis HTML로 생성해 브라우저에서 열기.
    반환: (node_count, edge_count)
    """
    global _last_html

    conn = sqlite3.connect(DB_PATH)
    note = conn.execute(
        "SELECT note_code, note_type, sender, receiver, title, content, note_date "
        "FROM notes WHERE note_code=?", (note_code,)
    ).fetchone()

    if not note:
        conn.close()
        return 0, 0

    _, ntype, sender, receiver, title, content, note_date = note
    full_text = (title or '') + ' ' + (content or '')

    q_kws = extract_keywords(query)
    n_kws = extract_keywords(full_text)
    n_set = set(n_kws)

    # 공통 키워드
    overlap = []
    for qk in q_kws:
        for nk in n_set:
            if qk in nk or nk in qk:
                overlap.append((qk, nk))
                break

    # 발신자 쪽지 (Hop 2)
    sender_notes = conn.execute(
        "SELECT note_code, title, note_date, receiver FROM notes "
        "WHERE sender=? AND note_code!=? ORDER BY note_date DESC LIMIT 4",
        (sender, note_code)
    ).fetchall()

    # 키워드 연결 쪽지 (Hop 3)
    kw_related = {}
    for _, nk in overlap[:3]:
        rows = conn.execute(
            "SELECT note_code, title, note_date, sender FROM notes "
            "WHERE (title LIKE ? OR content LIKE ?) AND note_code!=? LIMIT 3",
            (f'%{nk}%', f'%{nk}%', note_code)
        ).fetchall()
        if rows:
            kw_related[nk] = rows

    conn.close()

    # ── pyvis 네트워크 구성 ─────────────────────────────
    net = Network(
        height="100vh", width="100%",
        bgcolor="#1a1a2e", font_color="#ffffff",
        directed=True,
        notebook=False,
    )
    net.set_options("""
    {
      "nodes": {
        "borderWidth": 2,
        "shadow": { "enabled": true, "size": 10 },
        "font": { "size": 13, "face": "맑은 고딕, Malgun Gothic, sans-serif" }
      },
      "edges": {
        "arrows": { "to": { "enabled": true, "scaleFactor": 0.8 } },
        "smooth": { "type": "curvedCW", "roundness": 0.2 },
        "font": { "size": 11, "align": "middle", "color": "#cccccc" },
        "color": { "inherit": false }
      },
      "physics": {
        "enabled": true,
        "hierarchicalRepulsion": {
          "centralGravity": 0.3,
          "springLength": 130,
          "nodeDistance": 160
        },
        "solver": "hierarchicalRepulsion"
      },
      "layout": {
        "hierarchical": {
          "enabled": true,
          "direction": "UD",
          "sortMethod": "directed",
          "levelSeparation": 140,
          "nodeSpacing": 160
        }
      },
      "interaction": {
        "hover": true,
        "tooltipDelay": 100,
        "navigationButtons": true
      }
    }
    """)

    # ── 노드 추가 ──────────────────────────────────────
    # Hop 0: 쿼리
    q_label = query if len(query) <= 20 else query[:19] + "…"
    net.add_node(
        "query", label=f"🔍 {q_label}",
        color={"background": "#3a78c9", "border": "#5b9de0"},
        shape="box", size=28, level=0,
        title=f"<b>검색 쿼리</b><br>{query}"
    )

    # Hop 1: 매칭 쪽지
    note_id  = f"note_{note_code}"
    type_lbl = "받은" if ntype == "receive" else "보낸"
    n_title  = (title or "(제목없음)")[:24]
    score_str = f"유사도: {sim_score:.3f}" if sim_score is not None else ""
    net.add_node(
        note_id,
        label=f"📨 {n_title}",
        color={"background": "#1a9e5c", "border": "#2ecc71"},
        shape="box", size=24, level=1,
        title=(
            f"<b>[{type_lbl}쪽지]</b><br>"
            f"날짜: {_fmt_date(note_date)}<br>"
            f"보낸이: {sender}<br>받는이: {receiver}<br>"
            f"제목: {title or ''}<br>"
            f"내용: {(content or '')[:180]}{'…' if len(content or '') > 180 else ''}<br>"
            f"<i>{score_str}</i>"
        )
    )

    # Query → Note 엣지
    edge_lbl = f"{sim_score:.3f}" if sim_score is not None else "매칭"
    net.add_edge("query", note_id, label=edge_lbl, color="#3a78c9", width=3)

    # 발신자 노드 (Hop 2)
    person_id = f"person_{sender}"
    net.add_node(
        person_id,
        label=f"👤 {sender}",
        color={"background": "#c0392b", "border": "#e74c3c"},
        shape="ellipse", size=22, level=2,
        title=f"<b>발신자</b><br>{sender}<br>관련 쪽지 {len(sender_notes)}건"
    )
    net.add_edge(note_id, person_id, label="발신자", color="#e74c3c", width=2)

    # 키워드 노드 (Hop 2)
    added_kw = set()
    for qk, nk in overlap[:4]:
        kw_id = f"kw_{nk}"
        if kw_id not in added_kw:
            net.add_node(
                kw_id,
                label=f"🔑 {nk}",
                color={"background": "#7b2fa8", "border": "#9b59b6"},
                shape="ellipse", size=20, level=2,
                title=f"<b>공통 키워드</b><br>쿼리: \"{qk}\"<br>본문: \"{nk}\""
            )
            net.add_edge(note_id, kw_id, label="키워드", color="#9b59b6", width=2)
            added_kw.add(kw_id)

    # 발신자 → 연결 쪽지 (Hop 2 → 3)
    for rel_nc, rel_t, rel_d, rel_r in sender_notes[:3]:
        rid = f"rel_p_{rel_nc}"
        rt  = (rel_t or "(제목없음)")[:22]
        net.add_node(
            rid,
            label=f"📄 {rt}",
            color={"background": "#2c3e50", "border": "#7f8c8d"},
            shape="box", size=18, level=3,
            title=(
                f"<b>발신자 연결 쪽지</b><br>"
                f"날짜: {_fmt_date(rel_d)}<br>"
                f"제목: {rel_t or ''}<br>→ {rel_r}"
            )
        )
        net.add_edge(person_id, rid, color="#7f8c8d", width=1, dashes=True)

    # 키워드 → 연결 쪽지 (Hop 3)
    for nk, kw_notes in kw_related.items():
        kw_id = f"kw_{nk}"
        for rel_nc, rel_t, rel_d, rel_s in kw_notes[:2]:
            rid = f"rel_k_{rel_nc}_{nk[:4]}"
            rt  = (rel_t or "(제목없음)")[:22]
            net.add_node(
                rid,
                label=f"📄 {rt}",
                color={"background": "#1a3a4a", "border": "#5d6d7e"},
                shape="box", size=18, level=3,
                title=(
                    f"<b>키워드 \"{nk}\" 연결 쪽지</b><br>"
                    f"날짜: {_fmt_date(rel_d)}<br>"
                    f"제목: {rel_t or ''}<br>발신자: {rel_s}"
                )
            )
            if kw_id in added_kw:
                net.add_edge(kw_id, rid, color="#5d6d7e", width=1, dashes=True)

    # ── HTML 생성 & 브라우저 열기 ─────────────────────
    out_dir  = Path(__file__).parent / "graph_html"
    out_dir.mkdir(exist_ok=True)
    html_path = out_dir / f"hop_{note_code}.html"

    net.save_graph(str(html_path))
    webbrowser.open(html_path.as_uri())
    _last_html = html_path

    return len(net.nodes), len(net.edges)
