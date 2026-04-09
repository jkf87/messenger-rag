# Wiki Schema — 메신저 RAG 시맨틱 레이어

이 문서는 LLM이 wiki 페이지를 생성·갱신할 때 따르는 규칙을 정의합니다.
(Karpathy LLM Wiki 패턴 적용: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)

---

## 계층 구조

```
Layer 0: messages.db          ← 원본 SQLite (절대 수정 금지)
Layer 1: wiki/                ← LLM이 컴파일·유지하는 시맨틱 레이어
  ├── SCHEMA.md               ← 이 파일 (구조·규칙 정의)
  ├── index.md                ← 전체 페이지 카탈로그
  ├── log.md                  ← append-only 작업 로그
  ├── people/{이름}.md        ← 인물별 커뮤니케이션 프로필
  ├── topics/{주제}.md        ← 주제별 지식 합성
  └── timeline/{YYYY-MM}.md  ← 월별 활동 요약
Layer 2: 사용자 쿼리
```

---

## 페이지 형식

### people/{이름}.md

```markdown
---
type: person
name: {이름}
last_updated: {YYYY-MM-DD}
note_count: {N}
---

# {이름}

## 역할 및 위치
{조직 내 역할, 소속 추론}

## 주요 커뮤니케이션 패턴
{자주 발송하는 주제, 수신자 패턴}

## 주요 쪽지 요약
- [{note_code}] {제목} — {핵심 내용 1줄}
- ...

## 관련 인물
- [[{이름}]]: {관계 설명}

## 주요 주제
- [[{주제}]]: {관련도 설명}
```

### topics/{주제}.md

```markdown
---
type: topic
name: {주제}
last_updated: {YYYY-MM-DD}
note_count: {N}
---

# {주제}

## 개요
{이 주제가 무엇인지, 왜 중요한지}

## 주요 내용 요약
{핵심 정보, 결론, 수치 등}

## 관련 쪽지 목록
- [{note_code}] {제목} by {발신자} ({날짜})

## 관련 인물
- [[{이름}]]: {역할}

## 관련 주제
- [[{주제}]]
```

### timeline/{YYYY-MM}.md

```markdown
---
type: timeline
period: {YYYY-MM}
last_updated: {YYYY-MM-DD}
note_count: {N}
---

# {YYYY}년 {MM}월 활동 요약

## 주요 이벤트
- {날짜}: {이벤트}

## 핵심 주제
- [[{주제}]]

## 활동 인물
- [[{이름}]] ({건수}건)
```

---

## 규칙

1. **출처 표기**: 모든 주장은 `[note_code]` 또는 `[msg:{room_code}_{msg_time}]`로 인용
2. **상호 링크**: `[[페이지명]]` 형식으로 같은 wiki 내 페이지 참조
3. **사실 기반**: DB에 없는 내용은 추론임을 명시 (`[추론]` 태그)
4. **점진적 갱신**: 기존 페이지에 새 정보를 통합, 중복 제거
5. **간결성**: 각 페이지 500단어 이하 권장

---

## 인제스트 우선순위

1. 새 발신자 → people/ 페이지 생성
2. 제목에 키워드 포함된 쪽지 → topics/ 페이지 갱신
3. 날짜 범위 → timeline/ 페이지 갱신
4. 5건 이상 연결된 주제는 별도 topics/ 페이지로 분리

## 주제 추출 키워드

행사, 예산, 회의, 안내, 신청, 공문, 출장, 연수, 학생, 교육, 보고, 제출,
첨부, 결재, 협조, 업무, 계획, 일정, 학교, 교원, 학부모, 방학, 시험, 평가
