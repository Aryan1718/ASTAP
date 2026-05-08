from dataclasses import dataclass

from shared.config import GenerateTestsConfig
from shared.targets import GenerationPacket


SYSTEM_PROMPT = """You generate pytest files for a software testing platform.

Rules:
- output ONLY valid Python test code
- do not include markdown fences
- do not explain anything
- do not add prose outside code
- use pytest style
- keep imports minimal
- generate 3 to 6 tests per target when possible
- prefer simple, readable tests
- do not make external network calls
- do not perform destructive filesystem operations
- do not depend on unavailable services
- use mocking only when clearly needed
- avoid guessing hidden infrastructure
- if source context is limited, generate conservative tests that still form a valid pytest file
- when a security recipe is provided, generate focused abuse-case tests for that recipe only
- for security recipes, prefer 1 to 3 high-signal tests over broad coverage
"""


@dataclass(slots=True)
class OpenAIGenerateTestsProvider:
    api_key: str
    config: GenerateTestsConfig

    def generate_test_code(self, packet: GenerationPacket) -> str:
        return self._request(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=build_generation_prompt(packet),
        )

    def repair_test_code(self, *, packet: GenerationPacket, invalid_code: str, error_message: str) -> str:
        repair_prompt = "\n".join(
            [
                "Repair this pytest file so it is valid Python and still targets the same code.",
                "Return only Python code.",
                f"Validation error: {error_message}",
                "",
                "Original invalid code:",
                invalid_code,
                "",
                "Original generation packet:",
                build_generation_prompt(packet),
            ]
        )
        return self._request(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=repair_prompt,
        )

    def repair_collection_failure(
        self,
        *,
        generated_test_path: str,
        generated_test_code: str,
        error_message: str,
        target_key: str,
        target_type: str,
        symbol: str,
        source_file: str,
        generation_mode: str | None,
        recipe_id: str | None,
        recipe_name: str | None,
    ) -> str:
        repair_prompt = "\n".join(
            [
                "Repair this pytest file so pytest can collect and run it in the repo.",
                "Return only Python code.",
                "Fix only runnability issues such as imports, app/client wiring, fixtures, and import-time errors.",
                "Do not change the target under test.",
                "Do not convert the test into skip/xfail unless the repo wiring makes execution impossible without lying.",
                f"generated_test_path: {generated_test_path}",
                f"target_key: {target_key}",
                f"target_type: {target_type}",
                f"symbol: {symbol}",
                f"source_file: {source_file}",
                f"generation_mode: {generation_mode or 'unknown'}",
                f"recipe_id: {recipe_id or 'n/a'}",
                f"recipe_name: {recipe_name or 'n/a'}",
                "",
                "Pytest collection/setup error:",
                error_message,
                "",
                "Current generated test file:",
                generated_test_code,
            ]
        )
        return self._request(system_prompt=SYSTEM_PROMPT, user_prompt=repair_prompt)

    def _request(self, *, system_prompt: str, user_prompt: str) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        response = client.chat.completions.create(
            model=self.config.model,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError("OpenAI response did not include message content")
        return content.strip()


def build_generation_prompt(packet: GenerationPacket) -> str:
    target = packet.target_artifact
    source = packet.source_context
    if packet.generation_mode == "generic_fallback":
        test_instructions = [
            "Target-specific rules:",
            "- SERVICE_FUNCTION: create deterministic smoke or unit tests that import the symbol, call it conservatively, and assert basic behavior or explicit errors only when the source strongly implies them.",
            "- API_ENDPOINT: create lightweight request or response tests using the inferred framework test client only when app wiring is clearly inferable from the execution context.",
            "- Prefer narrow tests that are likely to run over broad semantic guesses.",
            "- Avoid external services, real network calls, or destructive filesystem behavior.",
        ]
    else:
        test_instructions = [
            "Target-specific rules:",
            "- SERVICE_FUNCTION: create deterministic unit tests that exercise the named security behavior against the function directly.",
            "- API_ENDPOINT: create pytest API tests. If framework hints include FastAPI, assume FastAPI TestClient patterns only when they can be inferred from source. Focus on abuse-case requests and secure-failure expectations.",
            "- If imports or app/client wiring are unclear, keep tests conservative and lightweight.",
        ]

    return "\n".join(
        [
            f"run_id: {packet.run_id}",
            f"generation_mode: {packet.generation_mode}",
            f"recipe_id: {packet.recipe_id or 'n/a'}",
            f"recipe_name: {packet.recipe_name or 'n/a'}",
            f"target_type: {target.target_type}",
            f"target_key: {target.target_key}",
            f"symbol: {target.symbol}",
            f"signature: {target.signature or 'unknown'}",
            f"file_path: {target.file_path}",
            f"line_range: {source.line_start}-{source.line_end}",
            f"framework_hints: {', '.join(target.framework_hints) if target.framework_hints else 'none'}",
            f"http_method: {target.http_method or 'n/a'}",
            f"route_path: {target.route_path or 'n/a'}",
            f"risk_tags: {', '.join(target.risk_tags) if target.risk_tags else 'none'}",
            f"input_sources: {', '.join(target.input_sources) if target.input_sources else 'none'}",
            f"dangerous_sinks: {', '.join(target.dangerous_sinks) if target.dangerous_sinks else 'none'}",
            f"execution_context: {target.execution_context}",
            f"recipe_payloads: {', '.join(packet.recipe_payload_templates) if packet.recipe_payload_templates else 'none'}",
            f"expected_secure_behaviors: {'; '.join(packet.recipe_expected_secure_behaviors) if packet.recipe_expected_secure_behaviors else 'none'}",
            f"recipe_rationale: {'; '.join(packet.recipe_rationale) if packet.recipe_rationale else 'none'}",
            "",
            *test_instructions,
            "",
            "Source context:",
            source.code,
        ]
    )
