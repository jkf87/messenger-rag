# -*- coding: utf-8 -*-
"""
로컬 RAG 검색 모듈
- intfloat/multilingual-e5-small 모델 사용
- 코사인 유사도 기반 시맨틱 검색
"""
import pickle, ssl, os
from pathlib import Path
import numpy as np

# 학교 네트워크 프록시 SSL 우회
ssl._create_default_https_context = ssl._create_unverified_context
os.environ.setdefault("CURL_CA_BUNDLE", "")
os.environ.setdefault("REQUESTS_CA_BUNDLE", "")
try:
    import httpx
    _orig = httpx.Client.__init__
    def _p(self, *a, **kw): kw.setdefault("verify", False); _orig(self, *a, **kw)
    httpx.Client.__init__ = _p
except Exception:
    pass

INDEX_PATH = Path(__file__).parent / "embed_index.pkl"
MODEL_NAME = "intfloat/multilingual-e5-small"

_index = None
_model = None

def _load():
    global _index, _model
    if _index is None:
        with open(INDEX_PATH, "rb") as f:
            _index = pickle.load(f)
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(_index.get("model", MODEL_NAME))
    return _index, _model

def is_index_ready():
    return INDEX_PATH.exists()

def _query_vec(q: str):
    _, model = _load()
    return model.encode([f"query: {q}"], normalize_embeddings=True)[0]

def rag_search_notes(q: str, note_type="all", sender="", top_k=30):
    """시맨틱 쪽지 검색. 반환: (rows, mode_label)"""
    idx, _ = _load()
    qv = _query_vec(q)
    scores = idx["note_embs"] @ qv          # 코사인 유사도 (정규화됐으므로 내적=코사인)
    order  = np.argsort(scores)[::-1]

    results = []
    for i in order:
        r = idx["notes"][i]
        # r: note_code, note_type, sender, receiver, title, content, note_date, file_cnt
        if note_type == "receive" and r[1] != "receive": continue
        if note_type == "send"    and r[1] != "send":    continue
        if sender and sender.lower() not in (r[2] or "").lower(): continue
        results.append(r)
        if len(results) >= top_k:
            break

    # read_yn 컬럼 삽입 (인덱스엔 없으므로 'Y' 플레이스홀더)
    # 순서: note_code, note_type, sender, receiver, title, content, note_date, [read_yn], file_cnt
    results = [r[:7] + ('Y',) + r[7:] for r in results]
    return results, "로컬RAG"

def rag_search_messages(q: str, room="", sender="", top_k=30):
    """시맨틱 메시지 검색. 반환: (rows, mode_label)"""
    idx, _ = _load()
    qv = _query_vec(q)
    scores = idx["msg_embs"] @ qv
    order  = np.argsort(scores)[::-1]

    results = []
    for i in order:
        r = idx["msgs"][i]
        # r: room_code, room_name, sender, content, msg_time, msg_date
        if room   and r[0] != room:                          continue
        if sender and sender.lower() not in (r[2] or "").lower(): continue
        results.append(r)
        if len(results) >= top_k:
            break

    return results, "로컬RAG"
