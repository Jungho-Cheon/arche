<!-- 이 파일은 `arche docs gen-reference` 가 코드 스키마에서 자동 생성합니다. 직접 고치지 마세요 — 모델을 바꾸고 명령을 다시 실행하세요. -->
<!-- source: apps/api/src/arche_api/docs_gen.py (#111) -->

> 아래 표는 코드의 스키마에서 자동 생성됩니다. 필드, 타입, 기본값, 범위는 언제나 실제 코드와 일치합니다.

### Node

| 필드 | 타입 | 기본값 | 제약 |
| --- | --- | --- | --- |
| `id` | `string` | (필수) | pattern `^[0-9A-Z]{26}$` |
| `name` | `string` | (필수) | 최대 200자 |
| `type` | `string` | (필수) | 최대 64자 |
| `aliases` | `string[]` | `[]` | — |
| `description` | `string \| null` | `null` (없으면 키 제외) | 최대 2000자 |
| `properties` | `object` | `{}` | — |
| `source_refs` | `SourceRef[]` | `[]` | — |
| `created_at` | `string` | (필수) | — |
| `updated_at` | `string` | (필수) | — |

### Edge

| 필드 | 타입 | 기본값 | 제약 |
| --- | --- | --- | --- |
| `id` | `string` | (필수) | pattern `^[0-9A-Z]{26}$` |
| `from` | `string` | (필수) | pattern `^[0-9A-Z]{26}$` |
| `to` | `string` | (필수) | pattern `^[0-9A-Z]{26}$` |
| `type` | `string` | (필수) | 최대 64자 |
| `properties` | `object` | `{}` | — |
| `source_refs` | `SourceRef[]` | `[]` | — |
| `created_at` | `string` | (필수) | — |
| `updated_at` | `string` | (필수) | — |

### SourceRef

| 필드 | 타입 | 기본값 | 제약 |
| --- | --- | --- | --- |
| `source_path` | `string` | (필수) | — |
| `chunk_index` | `int \| null` | `null` (없으면 키 제외) | — |
| `total_chunks` | `int \| null` | `null` (없으면 키 제외) | — |
