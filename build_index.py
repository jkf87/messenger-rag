# -*- coding: utf-8 -*-
"""
로컬 임베딩 인덱스 빌드
모델: intfloat/multilingual-e5-small (CPU)
대상: notes 테이블 전체 + messages 테이블
"""
import sys, sqlite3, pickle, time
from pathlib import Path

# 학교 네트워크 프록시 SSL 우회 (httpx + requests 모두 패치)
import ssl
ssl._create_default_https_context = ssl._create_unverified_context

import httpx
_orig_client_init = httpx.Client.__init__
def _patched_client_init(self, *args, **kwargs):
    kwargs.setdefault("verify", False)
    _orig_client_init(self, *args, **kwargs)
httpx.Client.__init__ = _patched_client_init

_orig_async_init = httpx.AsyncClient.__init__
def _patched_async_init(self, *args, **kwargs):
    kwargs.setdefault("verify", False)
    _orig_async_init(self, *args, **kwargs)
httpx.AsyncClient.__init__ = _patched_async_init

import os
os.environ["CURL_CA_BUNDLE"] = ""
os.environ["REQUESTS_CA_BUNDLE"] = ""

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
from sentence_transformers import SentenceTransformer

DB_PATH    = Path(__file__).parent / "messages.db"
INDEX_PATH = Path(__file__).parent / "embed_index.pkl"
MODEL_NAME = "intfloat/multilingual-e5-small"

print(f"모델 로드: {MODEL_NAME}")
t0 = time.time()
model = SentenceTransformer(MODEL_NAME)
print(f"  완료 ({time.time()-t0:.1f}s)\n")

conn = sqlite3.connect(DB_PATH)

# ── 쪽지 임베딩 ──────────────────────────────────────
print("쪽지 로드 중...")
notes = conn.execute(
    "SELECT note_code, note_type, sender, receiver, title, content, note_date, file_cnt FROM notes"
).fetchall()
print(f"  {len(notes)}건")

note_texts = [
    f"passage: {r[4]} {(r[5] or '')[:300]}"
    for r in notes
]

print("쪽지 임베딩 생성 중...")
t1 = time.time()
note_embs = model.encode(
    note_texts, batch_size=32,
    show_progress_bar=True,
    normalize_embeddings=True
)
print(f"  완료 ({time.time()-t1:.1f}s)  shape={note_embs.shape}\n")

# ── 메시지 임베딩 (최근 2000건만) ────────────────────
print("메시지 로드 중...")
msgs = conn.execute(
    "SELECT room_code, room_name, sender, content, msg_time, msg_date "
    "FROM messages ORDER BY msg_date DESC, msg_time DESC LIMIT 2000"
).fetchall()
print(f"  {len(msgs)}건")

msg_texts = [
    f"passage: {r[2]} {(r[3] or '')[:200]}"
    for r in msgs
]

print("메시지 임베딩 생성 중...")
t2 = time.time()
msg_embs = model.encode(
    msg_texts, batch_size=32,
    show_progress_bar=True,
    normalize_embeddings=True
)
print(f"  완료 ({time.time()-t2:.1f}s)  shape={msg_embs.shape}\n")

conn.close()

# ── 저장 ─────────────────────────────────────────────
index = {
    "model": MODEL_NAME,
    "notes": notes,
    "note_embs": note_embs,
    "msgs": msgs,
    "msg_embs": msg_embs,
}
with open(INDEX_PATH, "wb") as f:
    pickle.dump(index, f)

size_mb = INDEX_PATH.stat().st_size / 1024 / 1024
print(f"인덱스 저장 완료: {INDEX_PATH.name}  ({size_mb:.1f} MB)")
print(f"전체 소요: {time.time()-t0:.1f}s")
