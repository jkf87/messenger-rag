# -*- coding: utf-8 -*-
import sys, time
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import sqlite3
from pathlib import Path

queries = ['강사', '방송장비', '예산', '스키', '마이크', '수리', '구입신청', '훈련', '안전', '행사']
DB_PATH = Path(__file__).parent / "messages.db"

# ── 1. SQLite 키워드 검색 ─────────────────────────────
def kw_search(q):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT note_code,note_type,sender,receiver,title,content,note_date,read_yn,file_cnt "
        "FROM notes WHERE (title LIKE ? OR content LIKE ?) ORDER BY note_date DESC LIMIT 200",
        (f"%{q}%", f"%{q}%")
    ).fetchall()
    conn.close()
    return rows

kw_times, kw_counts = [], []
for q in queries:
    t0 = time.perf_counter()
    rows = kw_search(q)
    kw_times.append((time.perf_counter()-t0)*1000)
    kw_counts.append(len(rows))

# ── 2. pickle RAG ─────────────────────────────────────
import ssl, os
ssl._create_default_https_context = ssl._create_unverified_context
os.environ.setdefault("CURL_CA_BUNDLE", "")

from local_rag import _pickle_rag_search_notes, _grafeo_search_notes, _load, _query_vec
_load()
_query_vec("워밍업")  # 모델 워밍업

# ── Grafeo 임베딩 동기화 (같은 프로세스에서 직접 수행) ──
print("Grafeo 임베딩 동기화 중...", flush=True)
try:
    import numpy as np
    from grafeo_db import get_db, import_from_sqlite
    db = get_db()
    # 노드가 없으면 임포트
    r0 = db.execute("MATCH (n:Note) RETURN COUNT(n) AS cnt")
    note_cnt = next(iter(r0))['cnt']
    if note_cnt == 0:
        import_from_sqlite(str(DB_PATH))
    # 임베딩이 없으면 현재 프로세스에서 직접 저장
    r1 = db.execute("MATCH (n:Note) WHERE n.embedding IS NOT NULL RETURN COUNT(n) AS cnt")
    emb_cnt = next(iter(r1))['cnt']
    if emb_cnt == 0:
        idx, model = _load()
        for row, emb in zip(idx["notes"], idx["note_embs"]):
            db.execute(
                "MATCH (n:Note {note_code: $code}) SET n.embedding = vector($vec)",
                {"code": row[0], "vec": emb.tolist()}
            )
        print(f"  쪽지 임베딩 {len(idx['notes'])}건 저장 완료", flush=True)
    else:
        print(f"  임베딩 {emb_cnt}건 이미 존재", flush=True)
except Exception as e:
    print(f"  Grafeo 동기화 실패 (pickle 폴백): {e}", flush=True)

pk_times, pk_counts, pk_top1 = [], [], []
for q in queries:
    t0 = time.perf_counter()
    rows, _ = _pickle_rag_search_notes(q, top_k=30)
    pk_times.append((time.perf_counter()-t0)*1000)
    pk_counts.append(len(rows))
    pk_top1.append(rows[0][4][:22] if rows else "-")

# ── 3. Grafeo RAG ─────────────────────────────────────
gf_times, gf_counts, gf_top1 = [], [], []
for q in queries:
    t0 = time.perf_counter()
    rows, _ = _grafeo_search_notes(q, top_k=30)
    gf_times.append((time.perf_counter()-t0)*1000)
    gf_counts.append(len(rows))
    gf_top1.append(rows[0][4][:22] if rows else "-")

# ── 4. Top-5 겹침률 ───────────────────────────────────
overlaps = []
for q in queries:
    p5, _ = _pickle_rag_search_notes(q, top_k=5)
    g5, _ = _grafeo_search_notes(q, top_k=5)
    ps, gs = set(r[0] for r in p5), set(r[0] for r in g5)
    ov = len(ps & gs) / max(len(ps | gs), 1) * 100
    overlaps.append((q, ov, len(ps), len(gs)))

# ── 출력 ──────────────────────────────────────────────
sep = "─" * 72

print(sep)
print("  충북소통메신저 RAG 검색 벤치마크 리포트")
print(f"  대상: 쪽지 1,024건 / 테스트 쿼리 {len(queries)}개")
print(sep)

print("\n[1] 속도 비교 (ms, 쿼리당 평균)")
print(f"  {'방법':<22}  {'평균 응답':<10}  {'최소':<8}  {'최대'}")
print(f"  {'SQLite 키워드 (LIKE)':<22}  {sum(kw_times)/len(kw_times):>7.1f}ms  "
      f"{min(kw_times):>6.1f}ms  {max(kw_times):.1f}ms")
print(f"  {'pickle RAG (numpy)':<22}  {sum(pk_times)/len(pk_times):>7.1f}ms  "
      f"{min(pk_times):>6.1f}ms  {max(pk_times):.1f}ms")
print(f"  {'Grafeo RAG (벡터DB)':<22}  {sum(gf_times)/len(gf_times):>7.1f}ms  "
      f"{min(gf_times):>6.1f}ms  {max(gf_times):.1f}ms")

print("\n[2] 쿼리별 결과 건수 비교")
print(f"  {'쿼리':<12}  {'키워드':>6}  {'pickleRAG':>10}  {'GrafeoRAG':>10}")
print(f"  {'─'*12}  {'─'*6}  {'─'*10}  {'─'*10}")
for i, q in enumerate(queries):
    print(f"  {q:<12}  {kw_counts[i]:>6}건  {pk_counts[i]:>9}건  {gf_counts[i]:>9}건")
print(f"  {'평균':<12}  {sum(kw_counts)/len(kw_counts):>6.1f}건  "
      f"{sum(pk_counts)/len(pk_counts):>9.1f}건  {sum(gf_counts)/len(gf_counts):>9.1f}건")

print("\n[3] Top-1 결과 비교 (pickle vs Grafeo)")
print(f"  {'쿼리':<12}  {'pickle Top-1':<24}  {'Grafeo Top-1':<24}")
print(f"  {'─'*12}  {'─'*24}  {'─'*24}")
for i, q in enumerate(queries):
    match = "✓" if pk_top1[i] == gf_top1[i] else " "
    print(f"  {q:<12}  {pk_top1[i]:<24}  {gf_top1[i]:<24}  {match}")

print("\n[4] Top-5 결과 겹침률 (pickle ↔ Grafeo 일치도)")
print(f"  {'쿼리':<12}  {'겹침률':>8}  {'pickle5':>8}  {'Grafeo5':>8}")
print(f"  {'─'*12}  {'─'*8}  {'─'*8}  {'─'*8}")
for q, ov, ps, gs in overlaps:
    bar = "█" * int(ov/10) + "░" * (10-int(ov/10))
    print(f"  {q:<12}  {bar} {ov:>5.1f}%  {ps:>7}건  {gs:>7}건")
avg_ov = sum(o[1] for o in overlaps)/len(overlaps)
print(f"\n  평균 겹침률: {avg_ov:.1f}%")

print("\n[5] 종합 평가")
gf_faster = sum(pk_times)/len(pk_times) / max(sum(gf_times)/len(gf_times), 0.1)
print(f"  속도:  Grafeo가 pickle 대비 {gf_faster:.1f}배 {'빠름' if gf_faster>1 else '느림'}")
print(f"  일치도: 평균 {avg_ov:.1f}% — ",end="")
if avg_ov >= 80:
    print("두 방법의 결과가 거의 동일")
elif avg_ov >= 50:
    print("결과가 부분적으로 다름 (의미 기반 확장 효과 있음)")
else:
    print("결과가 크게 다름 (Grafeo가 더 넓은 의미 검색)")

kw_zero = sum(1 for c in kw_counts if c == 0)
pk_zero = sum(1 for c in pk_counts if c == 0)
gf_zero = sum(1 for c in gf_counts if c == 0)
print(f"  결과 없음: 키워드 {kw_zero}회, pickleRAG {pk_zero}회, GrafeoRAG {gf_zero}회")
print(sep)
