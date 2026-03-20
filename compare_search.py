# -*- coding: utf-8 -*-
"""
키워드 검색 vs 로컬 RAG 검색 성능 비교
결과를 search_comparison.md 로 저장
"""
import sys, sqlite3, time
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = Path(__file__).parent / "messages.db"

# ── 키워드 검색 ───────────────────────────────────────
def keyword_notes(q):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT note_code,note_type,sender,receiver,title,content,note_date,file_cnt "
        "FROM notes WHERE title LIKE ? OR content LIKE ? ORDER BY note_date DESC LIMIT 30",
        (f"%{q}%", f"%{q}%")
    ).fetchall()
    conn.close()
    return rows

# ── 로컬 RAG 검색 ─────────────────────────────────────
from local_rag import rag_search_notes

# ── 테스트 쿼리 ──────────────────────────────────────
QUERIES = [
    ("민방위 훈련",        "exact",    "정확한 키워드 포함 문서"),
    ("개인정보 보호",      "exact",    "정확한 키워드 포함 문서"),
    ("예산 편성",          "exact",    "정확한 키워드 포함 문서"),
    ("첨부파일 제출 요청", "semantic", "의미 기반 (다양한 표현 가능)"),
    ("안전 관련 교육",     "semantic", "의미 기반 (다양한 표현 가능)"),
    ("연수 신청 방법",     "semantic", "의미 기반 (다양한 표현 가능)"),
    ("방학 중 학생 지도",  "semantic", "의미 기반 (다양한 표현 가능)"),
]

results = []
print("비교 실행 중...\n")

for q, qtype, desc in QUERIES:
    # 키워드 검색
    t0 = time.time()
    kw_rows = keyword_notes(q)
    kw_time = (time.time() - t0) * 1000

    # RAG 검색
    t0 = time.time()
    rag_rows, _ = rag_search_notes(q, top_k=10)
    rag_time = (time.time() - t0) * 1000

    kw_titles  = [r[4][:35] for r in kw_rows[:3]]
    rag_titles = [r[4][:35] for r in rag_rows[:3]]

    results.append({
        "query":      q,
        "type":       qtype,
        "desc":       desc,
        "kw_cnt":     len(kw_rows),
        "kw_time":    kw_time,
        "kw_top3":    kw_titles,
        "rag_cnt":    len(rag_rows),
        "rag_time":   rag_time,
        "rag_top3":   rag_titles,
    })
    print(f"[{q}]  키워드={len(kw_rows)}건({kw_time:.0f}ms)  RAG={len(rag_rows)}건({rag_time:.0f}ms)")

# ── 마크다운 작성 ────────────────────────────────────
conn = sqlite3.connect(DB_PATH)
note_cnt = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
msg_cnt  = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
conn.close()

md = f"""# 키워드 검색 vs 로컬 RAG 검색 비교

## 테스트 환경

| 항목 | 내용 |
|------|------|
| DB | messages.db |
| 쪽지 수 | {note_cnt:,}건 |
| 메시지 수 | {msg_cnt:,}건 |
| 키워드 검색 | SQLite `LIKE '%q%'` |
| RAG 검색 | `intfloat/multilingual-e5-small` + 코사인 유사도 |
| 임베딩 차원 | 384 |
| 실행 환경 | CPU only (Windows) |

---

## 쿼리별 결과 비교

| # | 쿼리 | 유형 | 키워드 히트 | 키워드 응답 | RAG 히트 | RAG 응답 |
|---|------|------|------------|------------|---------|---------|
"""

for i, r in enumerate(results, 1):
    md += f"| {i} | {r['query']} | {r['type']} | {r['kw_cnt']}건 | {r['kw_time']:.0f}ms | {r['rag_cnt']}건 | {r['rag_time']:.0f}ms |\n"

md += "\n---\n\n## 쿼리별 상위 결과 상세\n\n"

for r in results:
    md += f"### \"{r['query']}\"  _{r['desc']}_\n\n"
    md += "**키워드 검색 상위 3건:**\n"
    if r["kw_top3"]:
        for t in r["kw_top3"]:
            md += f"- {t}\n"
    else:
        md += "- (결과 없음)\n"
    md += "\n**로컬 RAG 상위 3건:**\n"
    for t in r["rag_top3"]:
        md += f"- {t}\n"
    md += "\n"

md += """---

## 검색 방식별 특성 분석

### 키워드 검색 (SQLite LIKE)

| 항목 | 내용 |
|------|------|
| 속도 | 매우 빠름 (< 5ms) |
| 정확도 | 정확한 단어 포함 여부만 판단 |
| 장점 | 속도, 정확한 용어 검색, 별도 설치 불필요 |
| 단점 | 유의어·맥락 검색 불가 ("회의" ≠ "미팅"), 오타에 취약, 조사 변형 미처리 |
| 적합 | 특정 공문번호, 이름, 정확한 제목 검색 |

### 로컬 RAG (multilingual-e5-small)

| 항목 | 내용 |
|------|------|
| 속도 | 첫 로드 ~15s (모델 캐시), 이후 쿼리 < 100ms |
| 정확도 | 의미·맥락 기반, 유의어 인식 |
| 장점 | "첨부파일 제출" → "붙임 서류 제출하시기 바랍니다" 매칭, 한국어 지원 우수 |
| 단점 | 초기 모델 로드 시간, 정확한 고유명사 검색 시 키워드보다 낮을 수 있음 |
| 적합 | 내용 기반 탐색, 비슷한 의미 문서 발굴, "~에 관한 쪽지 찾기" |

---

## 결론 및 권장사항

### 용도별 추천

| 검색 목적 | 추천 방식 |
|----------|---------|
| 특정 단어/이름이 포함된 문서 | 키워드 검색 |
| "안전 교육 관련 쪽지 전부" | 로컬 RAG |
| 표현이 다양한 내용 탐색 | 로컬 RAG |
| 빠른 단순 검색 | 키워드 검색 |

### 현재 앱 적용 방법
- 검색창 옆 **"로컬 RAG" 체크박스** 체크 시 시맨틱 검색 전환
- 인덱스 파일(`embed_index.pkl`) 존재 시 자동 활성화
- 인덱스 재빌드: `python build_index.py` 재실행
"""

out = Path(__file__).parent / "search_comparison.md"
out.write_text(md, encoding="utf-8")
print(f"\n결과 저장: {out}")
