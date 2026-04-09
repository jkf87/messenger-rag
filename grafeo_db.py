# -*- coding: utf-8 -*-
"""
Grafeo 그래프 DB 레이어 (grafeo_db.py)
- messages.db(SQLite)에서 Grafeo 임베디드 그래프 DB로 데이터 임포트
- 그래프 스키마:
    노드  : Note, Person, Room, Message
    엣지  : (Person)-[:SENT]->(Note)
            (Note)-[:RECEIVED_BY]->(Person)
            (Person)-[:SENT_MSG]->(Message)
            (Message)-[:IN_ROOM]->(Room)
- grafeo 패키지 미설치 또는 DB 파일 없으면 graceful 폴백 (is_ready() → False)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List, Optional, Tuple

# ────────────────────────────────────────────────────────────────
# 경로 / 싱글턴
# ────────────────────────────────────────────────────────────────

_BASE_DIR       = Path(__file__).parent
_GRAFEO_DB_PATH = _BASE_DIR / "messenger_grafeo.db"

_db: object = None          # GrafeoDB 싱글턴 캐시


# ────────────────────────────────────────────────────────────────
# 내부 헬퍼 – Grafeo 노드 → Python 표준 타입 변환
# ────────────────────────────────────────────────────────────────

def _node_props(node) -> dict:
    """Grafeo 노드 객체에서 프로퍼티 dict 추출 (API 차이 대응)"""
    # 1) dict-like 직접 변환 시도
    try:
        return dict(node)
    except Exception:
        pass
    # 2) .properties 속성
    try:
        return node.properties
    except Exception:
        pass
    # 3) dict 키 접근
    try:
        return node["properties"]
    except Exception:
        pass
    return {}


def _row_props(row) -> dict:
    """execute() 결과 행(row)의 첫 번째 요소에서 노드 프로퍼티 추출"""
    # dict 형태 결과 (row["n"] 패턴)
    if isinstance(row, dict):
        for val in row.values():
            p = _node_props(val)
            if p:
                return p
        return {}
    # iterable 결과 (첫 원소가 노드)
    try:
        items = list(row)
        if items:
            return _node_props(items[0])
    except Exception:
        pass
    # 노드 자체가 row인 경우
    return _node_props(row)


def _to_note_tuple(props: dict) -> Tuple:
    """노드 프로퍼티 dict → 쪽지 표준 튜플"""
    return (
        props.get("note_code", ""),
        props.get("note_type", ""),
        props.get("sender",    ""),
        props.get("receiver",  ""),
        props.get("title",     ""),
        props.get("content",   ""),
        props.get("note_date", ""),
        props.get("read_yn",   ""),
        props.get("file_cnt",   0),
    )


def _to_msg_tuple(props: dict) -> Tuple:
    """노드 프로퍼티 dict → 메시지 표준 튜플"""
    return (
        props.get("room_code", ""),
        props.get("room_name", ""),
        props.get("sender",    ""),
        props.get("content",   ""),
        props.get("msg_time",  ""),
        props.get("msg_date",  ""),
    )


def _scalar(row) -> object:
    """execute() 스칼라 결과 행에서 첫 번째 값 추출"""
    if isinstance(row, dict):
        return next(iter(row.values()), None)
    try:
        return list(row)[0]
    except Exception:
        return row


# ────────────────────────────────────────────────────────────────
# 공개 API – 연결
# ────────────────────────────────────────────────────────────────

def get_db():
    """
    싱글턴 GrafeoDB 연결 반환.
    grafeo 미설치 / DB 파일 없으면 None 반환.
    """
    global _db
    if _db is not None:
        return _db
    try:
        import grafeo  # type: ignore
        _db = grafeo.GrafeoDB(str(_GRAFEO_DB_PATH))
        return _db
    except ImportError:
        # grafeo 패키지 미설치 – 조용히 무시
        return None
    except Exception as e:
        print(f"[grafeo_db] DB 연결 실패: {e}")
        return None


def is_ready() -> bool:
    """Grafeo DB 사용 가능 여부"""
    return get_db() is not None


# ────────────────────────────────────────────────────────────────
# SQLite → Grafeo 임포트
# ────────────────────────────────────────────────────────────────

def import_from_sqlite(sqlite_path: str = None) -> Tuple[int, int]:
    """
    기존 messages.db(SQLite)에서 데이터를 읽어 Grafeo로 임포트.
    - 트랜잭션 배치 처리 (500건씩)
    - 진행률 print
    반환: (imported_notes, imported_msgs)
    """
    db = get_db()
    if db is None:
        print("[grafeo_db] Grafeo DB를 사용할 수 없습니다.")
        return 0, 0

    if sqlite_path is None:
        sqlite_path = str(_BASE_DIR / "messages.db")

    if not Path(sqlite_path).exists():
        print(f"[grafeo_db] SQLite 파일 없음: {sqlite_path}")
        return 0, 0

    try:
        conn = sqlite3.connect(sqlite_path)
        conn.row_factory = sqlite3.Row
    except Exception as e:
        print(f"[grafeo_db] SQLite 연결 실패: {e}")
        return 0, 0

    BATCH = 500
    imported_notes = 0
    imported_msgs  = 0

    # ── 쪽지 임포트 ───────────────────────────────────────────────
    try:
        note_rows = conn.execute(
            "SELECT note_code, note_type, sender, receiver, title, content, "
            "       note_date, read_yn, file_cnt FROM notes"
        ).fetchall()
    except Exception as e:
        print(f"[grafeo_db] notes 테이블 읽기 실패: {e}")
        note_rows = []

    total_notes = len(note_rows)
    print(f"[grafeo_db] 쪽지 총 {total_notes}건 임포트 시작...")

    for start in range(0, total_notes, BATCH):
        batch = note_rows[start: start + BATCH]
        try:
            with db.begin_transaction() as tx:
                for row in batch:
                    code     = row["note_code"] or ""
                    sender   = row["sender"]    or ""
                    receiver = row["receiver"]  or ""

                    # Note 노드 upsert
                    tx.execute(
                        "MERGE (n:Note {note_code: $code}) "
                        "SET n.note_type = $ntype, n.sender = $sender, "
                        "    n.receiver  = $receiver, n.title = $title, "
                        "    n.content   = $content, n.note_date = $note_date, "
                        "    n.read_yn   = $read_yn, n.file_cnt = $file_cnt",
                        {
                            "code":      code,
                            "ntype":     row["note_type"]  or "",
                            "sender":    sender,
                            "receiver":  receiver,
                            "title":     row["title"]     or "",
                            "content":   row["content"]   or "",
                            "note_date": row["note_date"] or "",
                            "read_yn":   row["read_yn"]   or "",
                            "file_cnt":  row["file_cnt"]  or 0,
                        }
                    )
                    # 발신자 Person + [:SENT] 엣지
                    if sender:
                        tx.execute("MERGE (p:Person {name: $n})", {"n": sender})
                        tx.execute(
                            "MATCH (p:Person {name: $s}), (n:Note {note_code: $c}) "
                            "MERGE (p)-[:SENT]->(n)",
                            {"s": sender, "c": code}
                        )
                    # 수신자 Person + [:RECEIVED_BY] 엣지
                    if receiver:
                        tx.execute("MERGE (p:Person {name: $n})", {"n": receiver})
                        tx.execute(
                            "MATCH (n:Note {note_code: $c}), (p:Person {name: $r}) "
                            "MERGE (n)-[:RECEIVED_BY]->(p)",
                            {"c": code, "r": receiver}
                        )
                tx.commit()
            imported_notes += len(batch)
            pct = imported_notes / total_notes * 100 if total_notes else 100
            print(f"[grafeo_db] 쪽지 {imported_notes}/{total_notes} ({pct:.1f}%)")
        except Exception as e:
            print(f"[grafeo_db] 쪽지 배치 오류 (offset={start}): {e}")

    # ── 메시지 임포트 ─────────────────────────────────────────────
    try:
        msg_rows = conn.execute(
            "SELECT room_code, room_name, sender, content, msg_time, msg_date "
            "FROM messages"
        ).fetchall()
    except Exception as e:
        print(f"[grafeo_db] messages 테이블 읽기 실패: {e}")
        msg_rows = []

    total_msgs = len(msg_rows)
    print(f"[grafeo_db] 메시지 총 {total_msgs}건 임포트 시작...")

    for start in range(0, total_msgs, BATCH):
        batch = msg_rows[start: start + BATCH]
        try:
            with db.begin_transaction() as tx:
                for idx, row in enumerate(batch):
                    rcode   = row["room_code"] or ""
                    rname   = row["room_name"] or ""
                    sender  = row["sender"]    or ""
                    # 고유 키: room_code + msg_time + sender (upsert_message() / build_index.py와 통일)
                    mkey = f"{rcode}_{row['msg_time']}_{sender}"

                    # Room 노드 upsert
                    if rcode:
                        tx.execute(
                            "MERGE (r:Room {room_code: $rc}) SET r.room_name = $rn",
                            {"rc": rcode, "rn": rname}
                        )
                    # Message 노드 upsert
                    tx.execute(
                        "MERGE (m:Message {msg_key: $mkey}) "
                        "SET m.room_code = $rc, m.room_name = $rn, "
                        "    m.sender    = $sender, m.content  = $content, "
                        "    m.msg_time  = $mt,     m.msg_date = $md",
                        {
                            "mkey":    mkey,
                            "rc":      rcode,
                            "rn":      rname,
                            "sender":  sender,
                            "content": row["content"]  or "",
                            "mt":      row["msg_time"] or "",
                            "md":      row["msg_date"] or "",
                        }
                    )
                    # 발신자 Person + [:SENT_MSG] 엣지
                    if sender:
                        tx.execute("MERGE (p:Person {name: $n})", {"n": sender})
                        tx.execute(
                            "MATCH (p:Person {name: $s}), (m:Message {msg_key: $mk}) "
                            "MERGE (p)-[:SENT_MSG]->(m)",
                            {"s": sender, "mk": mkey}
                        )
                    # [:IN_ROOM] 엣지
                    if rcode:
                        tx.execute(
                            "MATCH (m:Message {msg_key: $mk}), (r:Room {room_code: $rc}) "
                            "MERGE (m)-[:IN_ROOM]->(r)",
                            {"mk": mkey, "rc": rcode}
                        )
                tx.commit()
            imported_msgs += len(batch)
            pct = imported_msgs / total_msgs * 100 if total_msgs else 100
            print(f"[grafeo_db] 메시지 {imported_msgs}/{total_msgs} ({pct:.1f}%)")
        except Exception as e:
            print(f"[grafeo_db] 메시지 배치 오류 (offset={start}): {e}")

    conn.close()
    print(f"[grafeo_db] 임포트 완료 — 쪽지 {imported_notes}건, 메시지 {imported_msgs}건")
    return imported_notes, imported_msgs


# ────────────────────────────────────────────────────────────────
# 쪽지 키워드 검색
# ────────────────────────────────────────────────────────────────

def search_notes_keyword(
    q:         str,
    note_type: str = "all",
    sender:    str = "",
    date_from: str = "",
    date_to:   str = "",
    limit:     int = 200,
) -> List[Tuple]:
    """
    Cypher CONTAINS 검색으로 쪽지 조회.
    날짜 범위: note_date는 '20260319151418891' 형식 문자열 비교.
    반환: list of (note_code, note_type, sender, receiver,
                   title, content, note_date, read_yn, file_cnt)
    """
    db = get_db()
    if db is None:
        return []

    try:
        conditions = ["(n.title CONTAINS $q OR n.content CONTAINS $q)"]
        params: dict = {"q": q}

        if note_type in ("receive", "send"):
            conditions.append("n.note_type = $note_type")
            params["note_type"] = note_type

        if sender:
            conditions.append("n.sender CONTAINS $sender")
            params["sender"] = sender

        if date_from:
            conditions.append("n.note_date >= $date_from")
            params["date_from"] = date_from

        if date_to:
            conditions.append("n.note_date <= $date_to")
            params["date_to"] = date_to

        where = " AND ".join(conditions)
        cypher = (
            f"MATCH (n:Note) WHERE {where} "
            f"RETURN n ORDER BY n.note_date DESC LIMIT {int(limit)}"
        )

        rows = []
        for row in db.execute(cypher, params):
            props = _row_props(row)
            if props:
                rows.append(_to_note_tuple(props))
        return rows

    except Exception as e:
        print(f"[grafeo_db] search_notes_keyword 오류: {e}")
        return []


# ────────────────────────────────────────────────────────────────
# 메시지 키워드 검색
# ────────────────────────────────────────────────────────────────

def search_messages_keyword(
    q:         str,
    room:      str = "",
    sender:    str = "",
    date_from: str = "",
    date_to:   str = "",
    limit:     int = 200,
) -> List[Tuple]:
    """
    Cypher CONTAINS 검색으로 메시지 조회.
    반환: list of (room_code, room_name, sender, content, msg_time, msg_date)
    """
    db = get_db()
    if db is None:
        return []

    try:
        conditions = ["m.content CONTAINS $q"]
        params: dict = {"q": q}

        if room:
            conditions.append("m.room_code = $room")
            params["room"] = room

        if sender:
            conditions.append("m.sender CONTAINS $sender")
            params["sender"] = sender

        if date_from:
            conditions.append("m.msg_date >= $date_from")
            params["date_from"] = date_from

        if date_to:
            conditions.append("m.msg_date <= $date_to")
            params["date_to"] = date_to

        where = " AND ".join(conditions)
        cypher = (
            f"MATCH (m:Message) WHERE {where} "
            f"RETURN m ORDER BY m.msg_time DESC LIMIT {int(limit)}"
        )

        rows = []
        for row in db.execute(cypher, params):
            props = _row_props(row)
            if props:
                rows.append(_to_msg_tuple(props))
        return rows

    except Exception as e:
        print(f"[grafeo_db] search_messages_keyword 오류: {e}")
        return []


# ────────────────────────────────────────────────────────────────
# 단건 조회
# ────────────────────────────────────────────────────────────────

def get_note_by_code(note_code: str) -> Optional[Tuple]:
    """
    note_code로 단일 쪽지 조회.
    반환: tuple(9개 필드) 또는 None
    """
    db = get_db()
    if db is None:
        return None
    try:
        for row in db.execute(
            "MATCH (n:Note {note_code: $c}) RETURN n LIMIT 1",
            {"c": note_code}
        ):
            props = _row_props(row)
            if props:
                return _to_note_tuple(props)
        return None
    except Exception as e:
        print(f"[grafeo_db] get_note_by_code 오류: {e}")
        return None


# ────────────────────────────────────────────────────────────────
# Graph RAG 보조 함수
# ────────────────────────────────────────────────────────────────

def get_person_notes(
    sender:       str,
    exclude_code: str = "",
    limit:        int = 4,
) -> List[Tuple]:
    """
    특정 발신자의 다른 쪽지들 조회 (Graph RAG Hop 2용).
    반환: list of (note_code, note_type, sender, receiver,
                   title, content, note_date, read_yn, file_cnt)
    """
    db = get_db()
    if db is None:
        return []
    try:
        params: dict = {"sender": sender}
        if exclude_code:
            cypher = (
                "MATCH (n:Note) "
                "WHERE n.sender = $sender AND n.note_code <> $excl "
                f"RETURN n ORDER BY n.note_date DESC LIMIT {int(limit)}"
            )
            params["excl"] = exclude_code
        else:
            cypher = (
                "MATCH (n:Note) "
                "WHERE n.sender = $sender "
                f"RETURN n ORDER BY n.note_date DESC LIMIT {int(limit)}"
            )
        rows = []
        for row in db.execute(cypher, params):
            props = _row_props(row)
            if props:
                rows.append(_to_note_tuple(props))
        return rows
    except Exception as e:
        print(f"[grafeo_db] get_person_notes 오류: {e}")
        return []


def keyword_related_notes(
    keyword:      str,
    exclude_code: str = "",
    limit:        int = 3,
) -> List[Tuple]:
    """
    특정 키워드를 포함한 쪽지들 조회 (Graph RAG Hop 3용).
    반환: list of (note_code, note_type, sender, receiver,
                   title, content, note_date, read_yn, file_cnt)
    """
    db = get_db()
    if db is None:
        return []
    try:
        params: dict = {"kw": keyword}
        if exclude_code:
            cypher = (
                "MATCH (n:Note) "
                "WHERE (n.title CONTAINS $kw OR n.content CONTAINS $kw) "
                "  AND n.note_code <> $excl "
                f"RETURN n ORDER BY n.note_date DESC LIMIT {int(limit)}"
            )
            params["excl"] = exclude_code
        else:
            cypher = (
                "MATCH (n:Note) "
                "WHERE (n.title CONTAINS $kw OR n.content CONTAINS $kw) "
                f"RETURN n ORDER BY n.note_date DESC LIMIT {int(limit)}"
            )
        rows = []
        for row in db.execute(cypher, params):
            props = _row_props(row)
            if props:
                rows.append(_to_note_tuple(props))
        return rows
    except Exception as e:
        print(f"[grafeo_db] keyword_related_notes 오류: {e}")
        return []


# ────────────────────────────────────────────────────────────────
# 통계 및 목록
# ────────────────────────────────────────────────────────────────

def get_stats() -> Tuple[int, int, int, list]:
    """
    DB 통계 반환.
    반환: (msg_total, note_total, room_count, room_list)
    room_list: [(room_code, room_name), ...]
    """
    db = get_db()
    if db is None:
        return (0, 0, 0, [])

    try:
        msg_total  = 0
        note_total = 0

        for row in db.execute("MATCH (m:Message) RETURN count(m) AS cnt"):
            try:
                msg_total = int(_scalar(row))
            except Exception:
                pass

        for row in db.execute("MATCH (n:Note) RETURN count(n) AS cnt"):
            try:
                note_total = int(_scalar(row))
            except Exception:
                pass

        room_list  = get_room_list()
        room_count = len(room_list)
        return (msg_total, note_total, room_count, room_list)

    except Exception as e:
        print(f"[grafeo_db] get_stats 오류: {e}")
        return (0, 0, 0, [])


def get_room_list() -> List[Tuple[str, str]]:
    """
    채팅방 목록 조회.
    반환: [(room_code, room_name), ...]
    """
    db = get_db()
    if db is None:
        return []
    try:
        rooms = []
        for row in db.execute("MATCH (r:Room) RETURN r ORDER BY r.room_name"):
            props = _row_props(row)
            if props:
                rooms.append((
                    props.get("room_code", ""),
                    props.get("room_name", ""),
                ))
        return rooms
    except Exception as e:
        print(f"[grafeo_db] get_room_list 오류: {e}")
        return []


# ────────────────────────────────────────────────────────────────
# Upsert
# ────────────────────────────────────────────────────────────────

def upsert_note(note_tuple: tuple) -> bool:
    """
    쪽지 추가/업데이트.
    note_tuple 순서: (note_code, note_type, sender, receiver, title,
                      content, note_date, read_yn, file_cnt)
    반환: 성공 여부
    """
    db = get_db()
    if db is None:
        return False
    if len(note_tuple) < 9:
        print("[grafeo_db] upsert_note: 튜플 9개 필드 필요")
        return False

    (note_code, note_type, sender, receiver, title,
     content, note_date, read_yn, file_cnt) = note_tuple[:9]
    code     = note_code or ""
    sender   = sender    or ""
    receiver = receiver  or ""

    try:
        with db.begin_transaction() as tx:
            tx.execute(
                "MERGE (n:Note {note_code: $code}) "
                "SET n.note_type = $ntype, n.sender = $sender, "
                "    n.receiver  = $receiver, n.title = $title, "
                "    n.content   = $content,  n.note_date = $note_date, "
                "    n.read_yn   = $read_yn,  n.file_cnt  = $file_cnt",
                {
                    "code":      code,
                    "ntype":     note_type  or "",
                    "sender":    sender,
                    "receiver":  receiver,
                    "title":     title      or "",
                    "content":   content    or "",
                    "note_date": note_date  or "",
                    "read_yn":   read_yn    or "",
                    "file_cnt":  file_cnt   or 0,
                }
            )
            if sender:
                tx.execute("MERGE (p:Person {name: $n})", {"n": sender})
                tx.execute(
                    "MATCH (p:Person {name: $s}), (n:Note {note_code: $c}) "
                    "MERGE (p)-[:SENT]->(n)",
                    {"s": sender, "c": code}
                )
            if receiver:
                tx.execute("MERGE (p:Person {name: $n})", {"n": receiver})
                tx.execute(
                    "MATCH (n:Note {note_code: $c}), (p:Person {name: $r}) "
                    "MERGE (n)-[:RECEIVED_BY]->(p)",
                    {"c": code, "r": receiver}
                )
            tx.commit()
        return True
    except Exception as e:
        print(f"[grafeo_db] upsert_note 오류: {e}")
        return False


def upsert_message(msg_tuple: tuple) -> bool:
    """
    메시지 추가/업데이트.
    msg_tuple 순서: (room_code, room_name, sender, content, msg_time, msg_date)
    반환: 성공 여부
    """
    db = get_db()
    if db is None:
        return False
    if len(msg_tuple) < 6:
        print("[grafeo_db] upsert_message: 튜플 6개 필드 필요")
        return False

    (room_code, room_name, sender, content, msg_time, msg_date) = msg_tuple[:6]
    rcode  = room_code or ""
    sender = sender    or ""
    # 고유 키: room_code + msg_time + sender
    mkey = f"{rcode}_{msg_time}_{sender}"

    try:
        with db.begin_transaction() as tx:
            if rcode:
                tx.execute(
                    "MERGE (r:Room {room_code: $rc}) SET r.room_name = $rn",
                    {"rc": rcode, "rn": room_name or ""}
                )
            tx.execute(
                "MERGE (m:Message {msg_key: $mkey}) "
                "SET m.room_code = $rc, m.room_name = $rn, "
                "    m.sender    = $sender, m.content  = $content, "
                "    m.msg_time  = $mt,     m.msg_date = $md",
                {
                    "mkey":    mkey,
                    "rc":      rcode,
                    "rn":      room_name  or "",
                    "sender":  sender,
                    "content": content    or "",
                    "mt":      msg_time   or "",
                    "md":      msg_date   or "",
                }
            )
            if sender:
                tx.execute("MERGE (p:Person {name: $n})", {"n": sender})
                tx.execute(
                    "MATCH (p:Person {name: $s}), (m:Message {msg_key: $mk}) "
                    "MERGE (p)-[:SENT_MSG]->(m)",
                    {"s": sender, "mk": mkey}
                )
            if rcode:
                tx.execute(
                    "MATCH (m:Message {msg_key: $mk}), (r:Room {room_code: $rc}) "
                    "MERGE (m)-[:IN_ROOM]->(r)",
                    {"mk": mkey, "rc": rcode}
                )
            tx.commit()
        return True
    except Exception as e:
        print(f"[grafeo_db] upsert_message 오류: {e}")
        return False


# ────────────────────────────────────────────────────────────────
# 벡터 인덱스 (선택적)
# ────────────────────────────────────────────────────────────────

def init_vector_index(dimension: int = 384) -> bool:
    """
    Note 노드에 코사인 유사도 벡터 인덱스 생성.
    이미 존재하면 무시. dimension은 임베딩 모델 출력 차원과 일치해야 함.
    """
    db = get_db()
    if db is None:
        return False
    try:
        db.execute(
            f"CREATE VECTOR INDEX note_vec ON :Note(embedding) "
            f"DIMENSION {dimension} METRIC 'cosine'"
        )
        print(f"[grafeo_db] 벡터 인덱스 생성 완료 (dimension={dimension})")
        return True
    except Exception as e:
        # 이미 존재하는 경우 등은 정상 – 메시지만 출력
        print(f"[grafeo_db] 벡터 인덱스 (이미 존재하거나 미지원): {e}")
        return False


def search_notes_vector(
    vec_list:  list,
    top_k:     int   = 30,
    threshold: float = 0.5,
) -> List[Tuple]:
    """
    벡터 유사도 기반 쪽지 검색 (벡터 인덱스 필요).
    반환: list of (note_tuple, score)
    """
    db = get_db()
    if db is None:
        return []
    try:
        cypher = (
            f"MATCH (n:Note) "
            f"WHERE cosine_similarity(n.embedding, vector({vec_list})) > {threshold} "
            f"RETURN n, cosine_similarity(n.embedding, vector({vec_list})) AS score "
            f"ORDER BY score DESC LIMIT {top_k}"
        )
        results = []
        for row in db.execute(cypher):
            try:
                items = list(row)
                if len(items) >= 2:
                    props = _node_props(items[0])
                    score = float(items[1])
                    if props:
                        results.append((_to_note_tuple(props), score))
            except Exception:
                pass
        return results
    except Exception as e:
        print(f"[grafeo_db] search_notes_vector 오류: {e}")
        return []
