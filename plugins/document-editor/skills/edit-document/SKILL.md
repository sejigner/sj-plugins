---
name: edit-document
description: |
  인터랙티브 문서 편집 스킬. 마크다운 문서를 웹 UI로 렌더링하여 문단별 수정 지시를 받고,
  AI 수정안을 제시한 뒤, 사용자 확인 후 원본 파일에 반영한다.
  "문서 편집해줘", "이 파일 수정해줘", "/edit-document", "인터랙티브 편집" 등으로 호출.
allowed-tools:
  - mcp__interactive_document_editor__collect_comments
  - mcp__interactive_document_editor__review_changes
  - Read
  - Edit
---

# Interactive Document Editor Skill

마크다운 문서를 웹 UI에서 인터랙티브하게 편집하는 스킬.

## Workflow

### Phase 1: Comment Collection

1. **파일 읽기**: `Read` 도구로 대상 마크다운 파일을 읽는다.
2. **코멘트 수집**: `mcp__interactive_document_editor__collect_comments`를 호출한다.
   ```
   mcp__interactive_document_editor__collect_comments({
     "content": "<마크다운 내용>",
     "title": "<파일명 또는 문서 제목>"
   })
   ```
3. 브라우저가 열리고 사용자가 문단별 수정 지시를 입력한다.
4. Submit 후 코멘트 목록이 반환된다:
   ```json
   {
     "status": "submitted",
     "comments": [
       {
         "paragraph_index": 0,
         "paragraph_text": "원본 마크다운 텍스트",
         "instruction": "사용자의 수정 지시"
       }
     ]
   }
   ```

### Phase 2: AI Revision

5. 각 코멘트에 대해 수정안을 생성한다:
   - `paragraph_text`(원본)와 `instruction`(지시)를 기반으로 수정안 작성
   - 전체 문서 컨텍스트를 고려하여 일관성 유지
   - 결과를 `changes` 배열로 구성:
     ```json
     [
       {
         "paragraph_index": 0,
         "original": "원본 텍스트",
         "suggested": "수정된 텍스트",
         "instruction": "사용자의 수정 지시"
       }
     ]
     ```

### Phase 3: Review

6. **리뷰 요청**: `mcp__interactive_document_editor__review_changes`를 호출한다.
   ```
   mcp__interactive_document_editor__review_changes({
     "changes": [위에서 구성한 changes 배열]
   })
   ```
7. 브라우저가 열리고 사용자가 각 변경사항을 Accept/Reject한다.
8. Submit 후 결정 목록이 반환된다:
   ```json
   {
     "status": "submitted",
     "decisions": [
       {
         "paragraph_index": 0,
         "original": "원본",
         "suggested": "수정안",
         "accepted": true
       }
     ]
   }
   ```

### Phase 4: Apply Changes

9. `accepted: true`인 항목만 `Edit` 도구로 원본 파일에 반영한다:
   ```
   Edit({
     "file_path": "<대상 파일 경로>",
     "old_string": "<original 텍스트>",
     "new_string": "<suggested 텍스트>"
   })
   ```
10. 결과를 요약하여 사용자에게 보고한다.

## Content Sources

1. **파일 경로 명시**: "이 파일 편집해줘: README.md" → Read로 읽기
2. **대화에서 파일 언급**: 최근 대화에서 언급된 파일 경로 사용
3. **직접 제공**: 사용자가 직접 마크다운 내용을 제공

## Important Notes

- `status: "cancelled"`가 반환되면 해당 Phase를 건너뛰고 사용자에게 알린다.
- `status: "timeout"`이면 시간 초과를 안내한다.
- Edit 도구 사용 시 `old_string`이 파일 내에서 고유한지 확인한다. 고유하지 않으면 주변 컨텍스트를 포함하여 고유하게 만든다.
- 수정안 생성 시 원본의 마크다운 서식(헤더, 리스트, 코드블록 등)을 보존한다.

## Response Template

모든 Phase 완료 후:

```
## 편집 결과

**적용된 변경**: X건
**거절된 변경**: Y건

### 적용된 변경사항:
1. [문단 #N]: [변경 요약]

### 거절된 변경사항:
1. [문단 #N]: [변경 요약]
```
