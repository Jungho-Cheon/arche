"""컬럼 (1) Full-context LLM — PRD 4 §1.

corpus 가 텍스트만이면 user 는 단일 문자열, PDF/이미지를 포함하면 멀티모달
content block 리스트로 LLM 에 전달한다. 시스템 프롬프트는 *측정 통제 변수*
(ADR-0001 D3) 라 모달이 바뀌어도 변하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..loaders import FileLoader, SerializedCorpus
from ..prompts import (
    FULL_CONTEXT_SYSTEM,
    RESPONSE_FORMAT_CHOICE_REASONING,
    build_full_context_user,
    render_options,
)
from ..providers import ContentBlock, LLMProvider, UserContent
from ..questions import Question


@dataclass
class FullContextRunner:
    loader: FileLoader
    llm: LLMProvider

    def setup_corpus(self) -> SerializedCorpus:
        """corpus 디스커버 + 직렬화 → 텍스트 블록 + 이미지 리스트.

        WHY 메서드 이름 변경 (setup_corpus_text → setup_corpus):
          반환이 단순 str → SerializedCorpus 로 바뀌었다. 이름이 *_text* 면 호출자가
          여전히 문자열 반환으로 오해할 위험. 시그니처와 이름을 같이 갱신.
        """
        files = self.loader.discover()
        return self.loader.serialize_corpus(files)

    # WHY 보조 별칭 유지: 본 PR 이전의 외부 호출자 (테스트 / CLI) 가 setup_corpus_text
    # 를 부른다. 한 번에 다 갱신하므로 별칭은 두지 않음 — 호출자도 같이 바꾼다.

    def ask(
        self,
        *,
        corpus: SerializedCorpus,
        question: Question,
        run_index: int,
    ) -> dict[str, Any]:
        options_block = render_options([(o.id, o.text) for o in question.options])
        text_user = build_full_context_user(
            corpus_text=corpus.text,
            question=question.question,
            options_block=options_block,
        )

        user_arg: UserContent
        if corpus.images:
            blocks: list[ContentBlock] = [{"type": "text", "text": text_user}]
            for img in corpus.images:
                blocks.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{img.mime_type};base64,{img.b64_data}"
                        },
                    }
                )
            user_arg = blocks
        else:
            user_arg = text_user

        result = self.llm.complete(
            system=FULL_CONTEXT_SYSTEM,
            user=user_arg,
            response_format=RESPONSE_FORMAT_CHOICE_REASONING,
        )
        # PRD 4 §1.5 스키마 + 디버그 보조 필드 (images_count).
        return {
            "column": "full_context",
            "question_id": question.id,
            "run_index": run_index,
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "latency_ms": result.latency_ms,
            "model": result.model,
            "raw_response": result.raw_response,
            "parsed": result.parsed,
            "parse_error": result.parse_error,
            # WHY images_count: spot-check / 디버깅 시 *이 호출이 멀티모달이었는가* 를
            # jsonl 한 줄만 보고 알 수 있게. PRD 4 §1.5 의 기존 키와 충돌 없음 (추가만).
            "images_count": len(corpus.images),
        }
