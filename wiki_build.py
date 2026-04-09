#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
wiki_build.py — Karpathy LLM Wiki 패턴 기반 시맨틱 레이어 빌더
참조: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f

계층:
  Layer 0: messages.db  (원본 SQLite — 불변)
  Layer 1: wiki/        (LLM이 컴파일·유지하는 마크다운 위키)
  Layer 2: 사용자 쿼리

사용법:
  python wiki_build.py ingest              # 새 데이터를 위키로 컴파일
  python wiki_build.py query "질문"        # 위키 검색 + LLM 답변 합성
  python wiki_build.py lint                # 위키 상태 검사
  python wiki_build.py status              # 통계 출력
"""

import sys, os, sqlite3, re, argparse, textwrap
from pathlib import Path
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── 경로 설정 ─────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
DB_PATH     = BASE_DIR / "messages.db"
WIKI_DIR    = BASE_DIR / "wiki"
SCHEMA_PATH = WIKI_DIR / "SCHEMA.md"
INDEX_PATH  = WIKI_DIR / "index.md"
LOG_PATH    = WIKI_DIR / "log.md"
PEOPLE_DIR  = WIKI_DIR / "people"
TOPICS_DIR  = WIKI_DIR / "topics"
TIMELINE_DIR= WIKI_DIR / "timeline"

ANTHROPIC_MODEL = "claude-sonnet-4-6"
GLM_MODEL = "glm-4.7"

# 주제 키워드 → 페이지명 매핑
TOPIC_KEYWORDS = {
    "예산": ["예산", "예산서", "결산", "지출"],
    "행사": ["행사", "체육대회", "졸업", "입학", "축제"],
    "회의": ["회의", "협의회", "위원회", "간담회", "자체연수"],
    "공문": ["공문", "공지", "안내", "알림"],
    "연수": ["연수", "교육", "워크숍", "직무"],
    "신청": ["신청", "접수", "제출", "등록"],
    "출장": ["출장", "출타", "외출"],
    "결재": ["결재", "품의", "승인", "검토"],
    "학생": ["학생", "학생부", "학생지도", "생활교육"],
    "학부모": ["학부모", "가정통신문", "학부형"],
    "CCTV": ["CCTV", "보안카메라", "영상"],
    "방학": ["방학", "개학"],
    "시험": ["시험", "평가", "성적", "지필"],
    "교원": ["교원", "교사", "선생님", "직원"],
    "보고": ["보고", "결과보고", "중간보고"],
}


# ── LLM 클라이언트 (Anthropic 우선, 없으면 GLM) ────────────
def _get_client():
    """(client, provider) 반환. provider: 'anthropic' | 'glm' | None"""
    # 1순위: Anthropic
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if anthropic_key:
        try:
            import anthropic
            return anthropic.Anthropic(api_key=anthropic_key), "anthropic"
        except ImportError:
            print("[경고] anthropic 패키지 없음: pip install anthropic")

    # 2순위: GLM (ZhipuAI)
    glm_key = os.environ.get("GLM_API_KEY", "")
    if glm_key:
        try:
            import zhipuai
            return zhipuai.ZhipuAI(api_key=glm_key), "glm"
        except ImportError:
            print("[경고] zhipuai 패키지 없음: pip install zhipuai")

    return None, None


def _llm(client_info, prompt: str, system: str = "") -> str:
    """LLM 단일 호출. client_info = (client, provider)"""
    if client_info is None:
        return ""
    client, provider = client_info
    if client is None:
        return ""

    if provider == "anthropic":
        kwargs = {
            "model": ANTHROPIC_MODEL,
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        resp = client.messages.create(**kwargs)
        return resp.content[0].text.strip()

    elif provider == "glm":
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = client.chat.completions.create(
            model=GLM_MODEL,
            messages=messages,
            max_tokens=8192,  # 추론 모델은 reasoning_content가 먼저 소모되므로 충분히 크게
        )
        content = resp.choices[0].message.content or ""
        return content.strip()

    return ""


# ── DB 접근 ───────────────────────────────────────────────
def _open_db():
    return sqlite3.connect(DB_PATH)


def _load_notes(since_date: str = "") -> list[dict]:
    """notes 테이블 전체(또는 since_date 이후) 로드."""
    conn = _open_db()
    sql = (
        "SELECT note_code, note_type, sender, receiver, title, "
        "content, note_date, read_yn, file_cnt FROM notes"
    )
    params = []
    if since_date:
        sql += " WHERE note_date > ?"
        params.append(since_date)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    keys = ["note_code", "note_type", "sender", "receiver", "title",
            "content", "note_date", "read_yn", "file_cnt"]
    return [dict(zip(keys, r)) for r in rows]


def _load_messages(since_date: str = "") -> list[dict]:
    conn = _open_db()
    sql = (
        "SELECT room_code, room_name, sender, content, msg_time, msg_date "
        "FROM messages"
    )
    params = []
    if since_date:
        sql += " WHERE msg_date > ?"
        params.append(since_date)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    keys = ["room_code", "room_name", "sender", "content", "msg_time", "msg_date"]
    return [dict(zip(keys, r)) for r in rows]


# ── 로그 ─────────────────────────────────────────────────
def _last_ingest_date() -> str:
    """log.md에서 마지막 ingest의 last_note_date 추출."""
    if not LOG_PATH.exists():
        return ""
    text = LOG_PATH.read_text(encoding="utf-8")
    matches = re.findall(r"last_note_date:\s*(\d+)", text)
    return matches[-1] if matches else ""


def _append_log(entry: str):
    """log.md 앞에 새 항목 추가 (최신이 위)."""
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    block = f"\n## {ts}\n{entry}\n\n---\n"
    text = LOG_PATH.read_text(encoding="utf-8")
    marker = "<!-- 이 아래로 wiki_build.py가 자동 추가 -->"
    if marker in text:
        new_text = text.replace(marker, marker + block)
    else:
        new_text = block + text
    LOG_PATH.write_text(new_text, encoding="utf-8")


# ── 날짜 포맷 ─────────────────────────────────────────────
def _fmt_date(d: str) -> str:
    """20260319151418891 → 2026-03-19"""
    if not d or len(d) < 8:
        return d or ""
    return f"{d[0:4]}-{d[4:6]}-{d[6:8]}"


def _month_key(d: str) -> str:
    """20260319151418891 → 2026-03"""
    if not d or len(d) < 6:
        return "unknown"
    return f"{d[0:4]}-{d[4:6]}"


# ── 주제 추출 ─────────────────────────────────────────────
def _extract_topics(title: str, content: str) -> list[str]:
    text = (title or "") + " " + (content or "")[:200]
    found = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            found.append(topic)
    return found


# ── 페이지 읽기/쓰기 ──────────────────────────────────────
def _read_page(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _write_page(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  ✓ {path.relative_to(BASE_DIR)}")


def _sanitize_filename(name: str) -> str:
    """파일명에 사용할 수 없는 문자 제거."""
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip()


# ── 인제스트: 인물 페이지 ─────────────────────────────────
def _ingest_person(client_info, name: str, notes: list[dict]):
    """발신자 한 명의 wiki 페이지를 생성/갱신."""
    path = PEOPLE_DIR / f"{_sanitize_filename(name)}.md"
    existing = _read_page(path)

    # 이 사람이 발송한 쪽지 요약 (최근 20건)
    sent = [n for n in notes if n["sender"] == name][:20]
    received = [n for n in notes if n["receiver"] == name][:10]

    note_lines = []
    for n in sent[:15]:
        title = (n["title"] or "").strip()
        content_preview = (n["content"] or "")[:80].replace("\n", " ").replace("\ufeff", "")
        date = _fmt_date(n["note_date"])
        note_lines.append(f"- [{n['note_code']}] {title} ({date}): {content_preview}")

    topics = set()
    for n in sent:
        topics.update(_extract_topics(n["title"], n["content"]))

    sent_to = {}
    for n in sent:
        rcv = n.get("receiver", "")
        if rcv:
            sent_to[rcv] = sent_to.get(rcv, 0) + 1

    raw_data = f"""발신자: {name}
발송 쪽지 수: {len(sent)}건
수신 쪽지 수: {len(received)}건
관련 주제: {', '.join(topics) if topics else '미분류'}
주요 수신자: {', '.join(f"{k}({v}건)" for k, v in sorted(sent_to.items(), key=lambda x: -x[1])[:5])}

발송 쪽지 목록:
{chr(10).join(note_lines)}
"""

    if client_info and client_info[0]:
        system = _read_page(SCHEMA_PATH)
        if existing and "## 역할 및 위치" in existing:
            prompt = f"""다음은 기존 wiki 페이지입니다:
{existing}

새로 추가된 데이터:
{raw_data}

기존 페이지에 새 정보를 통합하여 갱신된 페이지를 작성하세요.
SCHEMA.md의 people 페이지 형식을 따르세요. 한국어로 작성."""
        else:
            prompt = f"""다음 데이터를 바탕으로 인물 wiki 페이지를 작성하세요:
{raw_data}

SCHEMA.md의 people 페이지 형식을 따르세요. 역할은 발송 패턴에서 추론하세요. 한국어로 작성."""

        content = _llm(client_info, prompt, system=system)
    else:
        # API 없이 구조화된 기본 페이지 생성
        content = f"""---
type: person
name: {name}
last_updated: {datetime.now().strftime('%Y-%m-%d')}
note_count: {len(sent)}
---

# {name}

## 역할 및 위치
[추론 불가 — API 키 없음]

## 커뮤니케이션 통계
- 발송: {len(sent)}건
- 수신: {len(received)}건
- 주요 수신자: {', '.join(f"{k}({v}건)" for k, v in sorted(sent_to.items(), key=lambda x: -x[1])[:5])}

## 관련 주제
{chr(10).join(f'- [[{t}]]' for t in sorted(topics)) if topics else '- (없음)'}

## 발송 쪽지 목록
{chr(10).join(note_lines[:20])}
"""

    _write_page(path, content)


# ── 인제스트: 주제 페이지 ─────────────────────────────────
def _ingest_topic(client_info, topic: str, notes: list[dict]):
    """주제 wiki 페이지 생성/갱신."""
    path = TOPICS_DIR / f"{_sanitize_filename(topic)}.md"
    existing = _read_page(path)

    related = [
        n for n in notes
        if topic in _extract_topics(n["title"], n["content"])
    ][:30]

    if not related:
        return

    note_lines = []
    for n in related[:20]:
        title = (n["title"] or "").strip()
        date = _fmt_date(n["note_date"])
        content_preview = (n["content"] or "")[:100].replace("\n", " ").replace("\ufeff", "")
        note_lines.append(
            f"- [{n['note_code']}] {title} by {n['sender']} ({date})\n"
            f"  {content_preview}"
        )

    senders = list({n["sender"] for n in related})

    raw_data = f"""주제: {topic}
관련 쪽지 수: {len(related)}건
관련 발신자: {', '.join(senders[:10])}

관련 쪽지:
{chr(10).join(note_lines)}
"""

    if client_info and client_info[0]:
        system = _read_page(SCHEMA_PATH)
        if existing and "## 개요" in existing:
            prompt = f"""기존 wiki 페이지:
{existing}

새 데이터:
{raw_data}

기존 페이지에 새 정보를 통합하여 갱신하세요. topics 페이지 형식 준수. 한국어."""
        else:
            prompt = f"""다음 데이터로 주제 wiki 페이지를 작성하세요:
{raw_data}

SCHEMA.md의 topics 페이지 형식을 따르세요. 핵심 정보를 합성하세요. 한국어."""

        content = _llm(client_info, prompt, system=system)
    else:
        content = f"""---
type: topic
name: {topic}
last_updated: {datetime.now().strftime('%Y-%m-%d')}
note_count: {len(related)}
---

# {topic}

## 개요
[API 키 없음 — 자동 합성 불가]

## 관련 인물
{chr(10).join(f'- [[{s}]]' for s in senders[:10])}

## 관련 쪽지 목록
{chr(10).join(note_lines[:20])}
"""

    _write_page(path, content)


# ── 인제스트: 타임라인 페이지 ─────────────────────────────
def _ingest_timeline(client_info, month: str, notes: list[dict], msgs: list[dict]):
    """월별 타임라인 페이지 생성/갱신."""
    path = TIMELINE_DIR / f"{month}.md"
    existing = _read_page(path)

    month_notes = [n for n in notes if _month_key(n["note_date"]) == month]
    month_msgs  = [m for m in msgs  if _month_key(m.get("msg_date", "")) == month]

    if not month_notes and not month_msgs:
        return

    senders = {}
    for n in month_notes:
        senders[n["sender"]] = senders.get(n["sender"], 0) + 1

    topics = {}
    for n in month_notes:
        for t in _extract_topics(n["title"], n["content"]):
            topics[t] = topics.get(t, 0) + 1

    # 대표 쪽지 (제목 기준 상위 10건)
    sample_notes = []
    for n in month_notes[:10]:
        title = (n["title"] or "").strip()
        date = _fmt_date(n["note_date"])
        sample_notes.append(f"- [{n['note_code']}] {title} by {n['sender']} ({date})")

    raw_data = f"""기간: {month}
쪽지 수: {len(month_notes)}건, 메시지 수: {len(month_msgs)}건
활동 인물: {', '.join(f'{k}({v}건)' for k, v in sorted(senders.items(), key=lambda x:-x[1])[:8])}
주요 주제: {', '.join(f'{k}({v}건)' for k, v in sorted(topics.items(), key=lambda x:-x[1])[:8])}

대표 쪽지:
{chr(10).join(sample_notes)}
"""

    if client_info and client_info[0]:
        system = _read_page(SCHEMA_PATH)
        if existing and "## 주요 이벤트" in existing:
            prompt = f"""기존 타임라인 페이지:
{existing}

새 데이터:
{raw_data}

통합 갱신하세요. timeline 페이지 형식 준수. 한국어."""
        else:
            prompt = f"""다음 데이터로 월별 타임라인 wiki 페이지를 작성하세요:
{raw_data}

SCHEMA.md의 timeline 형식. 주요 이벤트와 흐름을 서술하세요. 한국어."""

        content = _llm(client_info, prompt, system=system)
    else:
        yr, mo = month.split("-")
        content = f"""---
type: timeline
period: {month}
last_updated: {datetime.now().strftime('%Y-%m-%d')}
note_count: {len(month_notes)}
---

# {yr}년 {mo}월 활동 요약

## 통계
- 쪽지: {len(month_notes)}건 / 메시지: {len(month_msgs)}건

## 활동 인물
{chr(10).join(f'- [[{k}]] ({v}건)' for k, v in sorted(senders.items(), key=lambda x:-x[1])[:10])}

## 주요 주제
{chr(10).join(f'- [[{k}]] ({v}건)' for k, v in sorted(topics.items(), key=lambda x:-x[1])[:8])}

## 대표 쪽지
{chr(10).join(sample_notes)}
"""

    _write_page(path, content)


# ── 인덱스 갱신 ──────────────────────────────────────────
def _update_index():
    """wiki/index.md를 현재 wiki 파일 목록으로 갱신."""
    def _list_section(directory: Path, section_title: str) -> str:
        lines = [f"## {section_title}\n"]
        pages = sorted(directory.glob("*.md"))
        for p in pages:
            text = _read_page(p)
            # frontmatter에서 note_count 추출
            m = re.search(r"note_count:\s*(\d+)", text)
            count = f" ({m.group(1)}건)" if m else ""
            # 첫 번째 # 제목 추출
            title_m = re.search(r"^# (.+)$", text, re.MULTILINE)
            title = title_m.group(1) if title_m else p.stem
            rel = p.relative_to(WIKI_DIR).as_posix()
            lines.append(f"- [{title}]({rel}){count}")
        return "\n".join(lines)

    people_sec   = _list_section(PEOPLE_DIR,   "인물 (People)")
    topics_sec   = _list_section(TOPICS_DIR,   "주제 (Topics)")
    timeline_sec = _list_section(TIMELINE_DIR, "타임라인 (Timeline)")

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    content = f"""# Wiki Index

> 마지막 갱신: {ts}
> `wiki_build.py ingest` 실행 시 자동 갱신됩니다.

---

{people_sec}

---

{topics_sec}

---

{timeline_sec}
"""
    INDEX_PATH.write_text(content, encoding="utf-8")
    print(f"  ✓ wiki/index.md 갱신")


# ══════════════════════════════════════════════════════════
# 커맨드: ingest
# ══════════════════════════════════════════════════════════
def cmd_ingest(args):
    """원본 DB → wiki 페이지 컴파일."""
    client_info = _get_client()
    client, provider = client_info if client_info != (None, None) else (None, None)
    if client:
        model = GLM_MODEL if provider == "glm" else ANTHROPIC_MODEL
        print(f"[LLM 연결됨] provider={provider}, 모델: {model}")
    else:
        print("[API 없음] 구조화된 기본 페이지를 생성합니다.")
        print("  → GLM_API_KEY 또는 ANTHROPIC_API_KEY 환경변수를 설정하면 LLM 합성이 활성화됩니다.\n")

    since = "" if args.full else _last_ingest_date()
    if since:
        print(f"마지막 인제스트 이후 데이터만 처리: {since}")
    else:
        print("전체 데이터 처리 중...")

    notes = _load_notes(since)
    msgs  = _load_messages(since)
    print(f"  쪽지: {len(notes)}건, 메시지: {len(msgs)}건\n")

    if not notes and not msgs:
        print("새 데이터 없음. 종료.")
        return

    updated_pages = []

    # 1) 인물 페이지
    all_senders = sorted({n["sender"] for n in notes if n["sender"]})
    print(f"[1/3] 인물 페이지 생성/갱신 ({len(all_senders)}명)...")
    all_notes_for_people = _load_notes()  # 전체 데이터로 인물 페이지는 항상 전체 기반
    for name in all_senders:
        _ingest_person(client_info, name, all_notes_for_people)
        updated_pages.append(f"people/{_sanitize_filename(name)}.md")

    # 2) 주제 페이지
    all_topics = set()
    for n in notes:
        all_topics.update(_extract_topics(n["title"], n["content"]))
    print(f"\n[2/3] 주제 페이지 생성/갱신 ({len(all_topics)}개)...")
    all_notes_for_topics = _load_notes()
    for topic in sorted(all_topics):
        _ingest_topic(client_info, topic, all_notes_for_topics)
        updated_pages.append(f"topics/{_sanitize_filename(topic)}.md")

    # 3) 타임라인 페이지
    all_months = sorted({_month_key(n["note_date"]) for n in notes if n["note_date"]})
    print(f"\n[3/3] 타임라인 페이지 생성/갱신 ({len(all_months)}개월)...")
    all_notes_for_tl = _load_notes()
    all_msgs_for_tl  = _load_messages()
    for month in all_months:
        if month and month != "unknown":
            _ingest_timeline(client_info, month, all_notes_for_tl, all_msgs_for_tl)
            updated_pages.append(f"timeline/{month}.md")

    # 4) 인덱스 갱신
    print("\n[인덱스 갱신]")
    _update_index()

    # 5) 로그 기록
    last_date = max((n["note_date"] for n in notes if n["note_date"]), default="")
    log_entry = f"""type: ingest
notes_processed: {len(notes)}
messages_processed: {len(msgs)}
pages_updated: {len(updated_pages)}
last_note_date: {last_date}
updated_pages:
{chr(10).join('  - ' + p for p in updated_pages[:30])}"""
    _append_log(log_entry)

    print(f"\n완료! {len(updated_pages)}개 페이지 갱신, 로그 기록됨.")


# ══════════════════════════════════════════════════════════
# 커맨드: query
# ══════════════════════════════════════════════════════════
def cmd_query(args):
    """wiki 검색 + LLM 답변 합성."""
    q = args.question
    print(f"쿼리: {q}\n")

    # 1) wiki 파일에서 관련 passages 수집 (키워드 매칭)
    q_words = set(q.lower().split())
    wiki_hits = []

    for md_path in WIKI_DIR.rglob("*.md"):
        if md_path.name in ("SCHEMA.md", "index.md", "log.md"):
            continue
        text = _read_page(md_path)
        # 쿼리 단어가 1개 이상 포함된 파일 수집
        if any(w in text.lower() for w in q_words if len(w) > 1):
            # 관련 문단 추출 (쿼리 단어 주변 300자)
            excerpt = []
            for w in q_words:
                if len(w) <= 1:
                    continue
                idx = text.lower().find(w)
                while idx != -1 and len(excerpt) < 3:
                    snippet = text[max(0, idx-50):idx+250].replace("\n", " ")
                    excerpt.append(snippet.strip())
                    idx = text.lower().find(w, idx + 1)
            rel_path = md_path.relative_to(WIKI_DIR).as_posix()
            wiki_hits.append({
                "page": rel_path,
                "excerpts": excerpt[:2],
            })

    if not wiki_hits:
        print("wiki에서 관련 페이지를 찾지 못했습니다.")
        print("→ python wiki_build.py ingest 를 먼저 실행하세요.\n")
        return

    print(f"관련 wiki 페이지 {len(wiki_hits)}개 발견:")
    for h in wiki_hits[:5]:
        print(f"  - {h['page']}")

    client_info = _get_client()
    client, provider = client_info if client_info != (None, None) else (None, None)
    if not client:
        print("\n[API 없음] wiki 페이지 발췌문을 출력합니다:\n")
        for h in wiki_hits[:3]:
            print(f"### {h['page']}")
            for ex in h["excerpts"]:
                print(f"  ...{ex}...")
            print()
        return

    # 2) 관련 wiki 내용 취합 (전체 페이지 텍스트)
    context_parts = []
    for h in wiki_hits[:6]:
        md_path = WIKI_DIR / h["page"]
        page_text = _read_page(md_path)
        page_text = re.sub(r"^---[\s\S]+?---\n", "", page_text)
        context_parts.append(f"=== {h['page']} ===\n{page_text[:1500]}")

    context = "\n\n".join(context_parts)

    system = """당신은 학교 행정 메신저 데이터를 기반으로 구축된 wiki의 검색 도우미입니다.
wiki의 내용을 근거로 답변하세요. 근거가 없는 추측은 [추론]으로 표시하세요.
wiki 페이지명을 출처로 인용하세요 (예: [people/김교사.md])."""

    prompt = f"""다음 wiki 내용을 참고하여 질문에 답하세요.

## Wiki 내용
{context}

## 질문
{q}

## 답변 형식
- 핵심 답변 (2-3문장)
- 관련 wiki 페이지: [페이지명]
- 관련 쪽지 코드 (있으면): [note_code]"""

    model_name = GLM_MODEL if provider == "glm" else ANTHROPIC_MODEL
    print(f"\n[{provider} ({model_name}) 답변 생성 중...]\n")
    answer = _llm(client_info, prompt, system=system)
    print(answer)

    # 쿼리를 log에 기록
    log_entry = f"""type: query
question: {q}
wiki_pages_searched: {len(wiki_hits)}
pages_used: {', '.join(h['page'] for h in wiki_hits[:6])}"""
    _append_log(log_entry)


# ══════════════════════════════════════════════════════════
# 커맨드: lint
# ══════════════════════════════════════════════════════════
def cmd_lint(args):
    """wiki 상태 검사."""
    print("Wiki 상태 검사 중...\n")
    issues = []

    # 1) 모든 wiki 페이지 수집
    all_pages = {
        p.relative_to(WIKI_DIR).as_posix()
        for p in WIKI_DIR.rglob("*.md")
        if p.name not in ("SCHEMA.md", "index.md", "log.md")
    }

    # 2) 링크 참조 검사 ([[PageName]] → 대응 파일 존재?)
    broken_links = []
    for md_path in WIKI_DIR.rglob("*.md"):
        if md_path.name in ("SCHEMA.md", "index.md", "log.md"):
            continue
        text = _read_page(md_path)
        refs = re.findall(r"\[\[([^\]]+)\]\]", text)
        for ref in refs:
            # people/ topics/ 두 곳에서 탐색
            found = (
                (PEOPLE_DIR / f"{_sanitize_filename(ref)}.md").exists() or
                (TOPICS_DIR / f"{_sanitize_filename(ref)}.md").exists()
            )
            if not found:
                broken_links.append((md_path.relative_to(WIKI_DIR).as_posix(), ref))

    # 3) 고아 페이지 (index.md에서 링크되지 않은 페이지)
    index_text = _read_page(INDEX_PATH)
    orphans = [p for p in all_pages if p.split("/")[-1].replace(".md", "") not in index_text]

    # 4) 오래된 페이지 (last_updated 기준 30일 초과)
    stale = []
    today_str = datetime.now().strftime("%Y-%m-%d")
    for md_path in WIKI_DIR.rglob("*.md"):
        text = _read_page(md_path)
        m = re.search(r"last_updated:\s*(\d{4}-\d{2}-\d{2})", text)
        if m:
            age_days = (
                datetime.strptime(today_str, "%Y-%m-%d") -
                datetime.strptime(m.group(1), "%Y-%m-%d")
            ).days
            if age_days > 30:
                stale.append((md_path.relative_to(WIKI_DIR).as_posix(), age_days))

    # 5) DB와 wiki 간 커버리지 확인
    all_senders = set()
    conn = _open_db()
    rows = conn.execute("SELECT DISTINCT sender FROM notes WHERE sender IS NOT NULL").fetchall()
    conn.close()
    all_senders = {r[0] for r in rows}
    covered_senders = {p.stem for p in PEOPLE_DIR.glob("*.md")}
    uncovered = all_senders - covered_senders

    # 리포트 출력
    print(f"총 wiki 페이지: {len(all_pages)}개")
    print(f"  - 인물: {len(list(PEOPLE_DIR.glob('*.md')))}개")
    print(f"  - 주제: {len(list(TOPICS_DIR.glob('*.md')))}개")
    print(f"  - 타임라인: {len(list(TIMELINE_DIR.glob('*.md')))}개")

    if broken_links:
        print(f"\n⚠ 깨진 링크 {len(broken_links)}개:")
        for page, ref in broken_links[:10]:
            print(f"  {page} → [[{ref}]]")
        issues.append(f"broken_links: {len(broken_links)}")

    if orphans:
        print(f"\n⚠ 고아 페이지 {len(orphans)}개:")
        for p in orphans[:10]:
            print(f"  {p}")
        issues.append(f"orphan_pages: {len(orphans)}")

    if stale:
        print(f"\n⚠ 오래된 페이지 {len(stale)}개 (30일 초과):")
        for p, days in sorted(stale, key=lambda x: -x[1])[:5]:
            print(f"  {p} ({days}일 전)")
        issues.append(f"stale_pages: {len(stale)}")

    if uncovered:
        print(f"\n⚠ wiki 미생성 발신자 {len(uncovered)}명:")
        print(f"  {', '.join(sorted(uncovered)[:10])}")
        issues.append(f"uncovered_senders: {len(uncovered)}")

    if not issues:
        print("\n✓ 이상 없음")
    else:
        print(f"\n→ python wiki_build.py ingest 로 갱신하세요.")

    log_entry = f"""type: lint
total_pages: {len(all_pages)}
issues: {'; '.join(issues) if issues else 'none'}"""
    _append_log(log_entry)


# ══════════════════════════════════════════════════════════
# 커맨드: status
# ══════════════════════════════════════════════════════════
def cmd_status(args):
    """wiki 통계 출력."""
    conn = _open_db()
    note_cnt = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    msg_cnt  = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    conn.close()

    people_pages   = list(PEOPLE_DIR.glob("*.md"))
    topic_pages    = list(TOPICS_DIR.glob("*.md"))
    timeline_pages = list(TIMELINE_DIR.glob("*.md"))
    last_date      = _last_ingest_date()

    print("=" * 50)
    print("Wiki 시맨틱 레이어 상태")
    print("=" * 50)
    print(f"\n[원본 데이터 — Layer 0]")
    print(f"  쪽지:    {note_cnt:,}건  (messages.db)")
    print(f"  메시지:  {msg_cnt:,}건  (messages.db)")

    print(f"\n[Wiki — Layer 1]")
    print(f"  인물 페이지:    {len(people_pages)}개  (wiki/people/)")
    print(f"  주제 페이지:    {len(topic_pages)}개  (wiki/topics/)")
    print(f"  타임라인 페이지:{len(timeline_pages)}개  (wiki/timeline/)")
    print(f"  마지막 ingest:  {_fmt_date(last_date) if last_date else '없음'}")

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    glm_key = os.environ.get("GLM_API_KEY", "")
    print(f"\n[LLM]")
    if anthropic_key:
        print(f"  Anthropic API: ✓  모델: {ANTHROPIC_MODEL}")
    elif glm_key:
        print(f"  GLM API: ✓  모델: {GLM_MODEL}")
    else:
        print(f"  LLM: ✗ 없음 (GLM_API_KEY 또는 ANTHROPIC_API_KEY 미설정)")

    print(f"\n[사용 가능한 명령]")
    print(f"  python wiki_build.py ingest       # 전체 인제스트")
    print(f"  python wiki_build.py ingest --full # 강제 전체 재빌드")
    print(f"  python wiki_build.py query \"질문\"  # wiki 검색")
    print(f"  python wiki_build.py lint          # 상태 검사")


# ══════════════════════════════════════════════════════════
# 진입점
# ══════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(
        description="Messenger RAG Wiki 시맨틱 레이어 빌더",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            예시:
              python wiki_build.py status
              python wiki_build.py ingest
              python wiki_build.py ingest --full
              python wiki_build.py query "예산 관련 공문을 누가 보냈나요?"
              python wiki_build.py lint
        """),
    )
    sub = parser.add_subparsers(dest="cmd")

    p_ingest = sub.add_parser("ingest", help="원본 DB → wiki 페이지 컴파일")
    p_ingest.add_argument("--full", action="store_true", help="전체 재빌드 (증분 무시)")

    p_query = sub.add_parser("query", help="wiki 검색 + LLM 답변")
    p_query.add_argument("question", help="질문 (한국어 가능)")

    sub.add_parser("lint", help="wiki 상태 검사")
    sub.add_parser("status", help="통계 출력")

    args = parser.parse_args()

    if args.cmd == "ingest":
        cmd_ingest(args)
    elif args.cmd == "query":
        cmd_query(args)
    elif args.cmd == "lint":
        cmd_lint(args)
    elif args.cmd == "status":
        cmd_status(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
