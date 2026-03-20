# -*- coding: utf-8 -*-
"""
GraphWidget - Neo4j 스타일 인터랙티브 그래프 위젯
- tkinter Canvas 기반 (외부 의존성 없음)
- 노드 드래그, 호버 툴팁 지원
- 다크 테마
"""
import tkinter as tk
import re

BG = "#1a1a2e"

COLORS = {
    "query":   {"fill": "#3a78c9", "outline": "#7ab0e8", "text": "white"},
    "note":    {"fill": "#1a7a4a", "outline": "#2ecc71", "text": "white"},
    "person":  {"fill": "#9b2335", "outline": "#e74c3c", "text": "white"},
    "keyword": {"fill": "#6a1fa8", "outline": "#b07dd4", "text": "white"},
    "related": {"fill": "#223344", "outline": "#4a6070", "text": "#aac8dd"},
}

EDGE_COLORS = {
    "similarity":  "#5b9de0",
    "person":      "#e74c3c",
    "keyword":     "#b07dd4",
    "person_rel":  "#c0392b",
    "keyword_rel": "#8e44ad",
}

SHAPES = {
    "query":   "rect",
    "note":    "rect",
    "person":  "oval",
    "keyword": "oval",
    "related": "rect",
}

# 레이어별 y 위치 (hierarchical layout)
LAYER_Y = {0: 70, 1: 190, 2: 330, 3: 460}
NODE_LAYER = {"query": 0, "note": 1, "person": 2, "keyword": 2, "related": 3}


class GraphWidget(tk.Frame):
    """Neo4j 스타일 인터랙티브 그래프 위젯"""

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=BG)

        # 스크롤바
        self._vbar = tk.Scrollbar(self, orient="vertical")
        self._hbar = tk.Scrollbar(self, orient="horizontal")
        self._canvas = tk.Canvas(self, bg=BG, highlightthickness=0,
                                  yscrollcommand=self._vbar.set,
                                  xscrollcommand=self._hbar.set)
        self._vbar.config(command=self._canvas.yview)
        self._hbar.config(command=self._canvas.xview)

        self._hbar.pack(side="bottom", fill="x")
        self._vbar.pack(side="right",  fill="y")
        self._canvas.pack(fill="both", expand=True)

        self._nodes   = {}   # id -> {x,y,w,h,shape,label,detail,type}
        self._edges   = []   # [{from,to,type,label}]
        self._drag    = None
        self._tooltip = None
        self._hovered = None

        self._canvas.bind("<Configure>",       self._on_resize)
        self._canvas.bind("<ButtonPress-1>",   self._on_press)
        self._canvas.bind("<B1-Motion>",       self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<Motion>",          self._on_motion)
        self._canvas.bind("<Leave>",           self._on_leave)
        self._canvas.bind("<MouseWheel>",      self._on_scroll)

    # ── 공개 API ──────────────────────────────────────
    def set_graph(self, data: dict, layout: str = "auto"):
        """
        layout: "auto" | "hierarchical" | "radial"
        auto = 쿼리 노드만 있으면 radial, 나머지는 hierarchical
        """
        self._nodes.clear()
        self._edges.clear()
        if not data or not data.get("nodes"):
            self._canvas.delete("all")
            self._draw_placeholder()
            return
        for n in data.get("nodes", []):
            label = n["label"]
            w = self._node_w(label, n["type"])
            h = self._node_h(label, n["type"])
            self._nodes[n["id"]] = {
                "x": 0, "y": 0, "w": w, "h": h,
                "shape": SHAPES.get(n["type"], "rect"),
                "label": label,
                "detail": _strip_html(n.get("detail", "")),
                "type":  n["type"],
            }
        self._edges = data.get("edges", [])

        # 레이아웃 자동 결정: note 노드가 많으면 radial
        if layout == "auto":
            note_count = sum(1 for n in data["nodes"] if n["type"] == "note")
            layout = "radial" if note_count >= 5 else "hierarchical"
        self._layout_mode = layout

        W = max(self._canvas.winfo_width(), 320)
        if layout == "radial":
            self._layout_radial(W)
        else:
            self._layout(W)
        self._redraw()

    def clear(self):
        self._nodes.clear()
        self._edges.clear()
        self._canvas.delete("all")
        self._draw_placeholder()

    # ── 레이아웃 ──────────────────────────────────────
    def _layout(self, W=None):
        W = W or max(self._canvas.winfo_width(), 320)
        MARGIN = 50

        # 레이어별 노드 그룹
        layers = {}
        for nid, nd in self._nodes.items():
            ly = NODE_LAYER.get(nd["type"], 3)
            layers.setdefault(ly, []).append(nid)

        # 레이어 3에 노드가 많을 경우 캔버스 너비 확장
        max_layer_count = max((len(v) for v in layers.values()), default=1)
        min_spacing = 160
        effective_w = max(W, max_layer_count * min_spacing + 2 * MARGIN)

        for li in sorted(layers.keys()):
            cy = LAYER_Y.get(li, LAYER_Y[3] + (li - 3) * 140)
            nids = layers[li]
            if len(nids) == 1:
                xs = [effective_w // 2]
            else:
                step = (effective_w - 2 * MARGIN) / (len(nids) - 1)
                xs = [int(MARGIN + i * step) for i in range(len(nids))]
            for i, nid in enumerate(nids):
                self._nodes[nid]["x"] = xs[i]
                self._nodes[nid]["y"] = cy

    def _layout_radial(self, W=None):
        """쿼리를 중심에, 나머지 노드를 원형으로 배치"""
        import math
        W = W or max(self._canvas.winfo_width(), 320)
        H = max(self._canvas.winfo_height(), 400)
        cx, cy = W // 2, H // 2

        # 쿼리 노드 중심
        if "query" in self._nodes:
            self._nodes["query"]["x"] = cx
            self._nodes["query"]["y"] = cy

        others = [nid for nid in self._nodes if nid != "query"]
        if not others:
            return

        n = len(others)
        r = min(W, H) // 2 - 70  # 반지름
        for i, nid in enumerate(others):
            angle = 2 * math.pi * i / n - math.pi / 2
            self._nodes[nid]["x"] = int(cx + r * math.cos(angle))
            self._nodes[nid]["y"] = int(cy + r * math.sin(angle))

    def _on_resize(self, event=None):
        W = event.width if event else None
        if self._nodes:
            mode = getattr(self, "_layout_mode", "hierarchical")
            if mode == "radial":
                self._layout_radial(W)
            else:
                self._layout(W)
            self._redraw()
        else:
            self._canvas.delete("all")
            self._draw_placeholder()

    # ── 그리기 ────────────────────────────────────────
    def _redraw(self):
        c = self._canvas
        c.delete("all")
        if not self._nodes:
            self._draw_placeholder()
            return

        self._draw_edges()
        self._draw_nodes()

        # 스크롤 영역 갱신
        xs = [nd["x"] for nd in self._nodes.values()]
        ys = [nd["y"] for nd in self._nodes.values()]
        ws = [nd["w"] for nd in self._nodes.values()]
        hs = [nd["h"] for nd in self._nodes.values()]
        x1 = min(x - w // 2 for x, w in zip(xs, ws)) - 30
        y1 = min(y - h // 2 for y, h in zip(ys, hs)) - 30
        x2 = max(x + w // 2 for x, w in zip(xs, ws)) + 30
        y2 = max(y + h // 2 for y, h in zip(ys, hs)) + 30
        c.configure(scrollregion=(x1, y1, x2, y2))

    def _draw_placeholder(self):
        W = max(self._canvas.winfo_width(), 320)
        H = max(self._canvas.winfo_height(), 200)
        self._canvas.create_text(
            W // 2, H // 2,
            text="쪽지를 클릭하면\n그래프가 표시됩니다",
            font=("맑은 고딕", 11), fill="#3a4a6a", justify="center"
        )

    def _draw_nodes(self):
        for nid, nd in self._nodes.items():
            cx, cy, w, h = nd["x"], nd["y"], nd["w"], nd["h"]
            col   = COLORS.get(nd["type"], COLORS["related"])
            shape = nd["shape"]
            tags  = ("node", nid)

            if shape == "oval":
                r = min(w, h) // 2
                self._canvas.create_oval(
                    cx - r, cy - r, cx + r, cy + r,
                    fill=col["fill"], outline=col["outline"], width=2, tags=tags
                )
            else:
                x1, y1, x2, y2 = cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2
                self._rounded_rect(x1, y1, x2, y2, 10,
                                   fill=col["fill"], outline=col["outline"],
                                   width=2, tags=tags)

            self._canvas.create_text(
                cx, cy, text=nd["label"],
                font=("맑은 고딕", 9), fill=col["text"],
                justify="center", width=w - 14, tags=tags
            )

    def _draw_edges(self):
        for e in self._edges:
            src = self._nodes.get(e["from"])
            tgt = self._nodes.get(e["to"])
            if not src or not tgt:
                continue

            color = EDGE_COLORS.get(e.get("type", ""), "#4a6070")
            sx, sy_ = src["x"], src["y"] + src["h"] // 2
            tx, ty_ = tgt["x"], tgt["y"] - tgt["h"] // 2
            dy = ty_ - sy_
            cp1y = sy_ + dy * 0.4
            cp2y = ty_ - dy * 0.4

            self._canvas.create_line(
                sx, sy_, sx, cp1y, tx, cp2y, tx, ty_,
                smooth=True, fill=color, width=2,
                arrow="last", arrowshape=(9, 12, 4), tags="edge"
            )

            lbl = e.get("label", "")
            if lbl:
                mx = (sx + tx) // 2
                my = (sy_ + ty_) // 2
                self._canvas.create_text(
                    mx + 5, my, text=lbl,
                    font=("맑은 고딕", 8), fill=color, anchor="w", tags="edge"
                )

    def _rounded_rect(self, x1, y1, x2, y2, r, **kw):
        self._canvas.create_polygon(
            x1 + r, y1,     x2 - r, y1,
            x2,     y1 + r, x2,     y2 - r,
            x2 - r, y2,     x1 + r, y2,
            x1,     y2 - r, x1,     y1 + r,
            smooth=True, **kw
        )

    # ── 노드 크기 계산 ────────────────────────────────
    def _node_w(self, label, ntype):
        lines = label.split("\n")
        char_w = max(len(l) for l in lines) * 10 + 28
        if ntype in ("person", "keyword"):
            text_h = len(lines) * 20 + 18
            return max(char_w, text_h, 70)   # 정사각형 기반
        return max(char_w, 100)

    def _node_h(self, label, ntype):
        if ntype in ("person", "keyword"):
            return self._node_w(label, ntype)  # 너비=높이 (원형)
        n_lines = len(label.split("\n"))
        return max(n_lines * 20 + 18, 36)

    # ── 인터랙션 ──────────────────────────────────────
    def _hit_node(self, ex, ey):
        cx_ev = self._canvas.canvasx(ex)
        cy_ev = self._canvas.canvasy(ey)
        for nid, nd in self._nodes.items():
            if (abs(cx_ev - nd["x"]) <= nd["w"] // 2 and
                    abs(cy_ev - nd["y"]) <= nd["h"] // 2):
                return nid
        return None

    def _on_press(self, event):
        nid = self._hit_node(event.x, event.y)
        self._drag = {"id": nid, "ex": event.x, "ey": event.y} if nid else None

    def _on_drag(self, event):
        if self._drag:
            dx = event.x - self._drag["ex"]
            dy = event.y - self._drag["ey"]
            self._nodes[self._drag["id"]]["x"] += dx
            self._nodes[self._drag["id"]]["y"] += dy
            self._drag["ex"] = event.x
            self._drag["ey"] = event.y
            self._redraw()

    def _on_release(self, event):
        self._drag = None

    def _on_motion(self, event):
        nid = self._hit_node(event.x, event.y)
        if nid != self._hovered:
            self._hovered = nid
            self._hide_tooltip()
            if nid and self._nodes[nid].get("detail"):
                self._show_tooltip(event.x_root + 14, event.y_root + 14,
                                   self._nodes[nid]["detail"])

    def _on_leave(self, event):
        self._hovered = None
        self._hide_tooltip()

    def _on_scroll(self, event):
        self._canvas.yview_scroll(-1 * (event.delta // 120), "units")

    def _show_tooltip(self, x, y, text):
        self._hide_tooltip()
        tw = tk.Toplevel(self._canvas)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(tw, text=text, bg="#1e2a3a", fg="#c8e0ff",
                 font=("맑은 고딕", 9), relief="solid", bd=1,
                 padx=10, pady=6, wraplength=320, justify="left").pack()
        self._tooltip = tw

    def _hide_tooltip(self, _=None):
        if self._tooltip:
            try:
                self._tooltip.destroy()
            except Exception:
                pass
            self._tooltip = None


def _strip_html(text):
    clean = re.sub(r'<[^>]+>', '\n', text)
    clean = clean.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>')
    return re.sub(r'\n{3,}', '\n\n', clean).strip()
