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
    test_instructions = [
        "Target-specific rules:",
        "- SERVICE_FUNCTION: create deterministic unit tests with happy path, edge case, and invalid input or exception coverage where appropriate.",
        "- API_ENDPOINT: create pytest API tests. If framework hints include FastAPI, assume FastAPI TestClient patterns only when they can be inferred from source. Include valid request, invalid request or validation error, status code checks, and JSON shape checks.",
        "- If imports or app/client wiring are unclear, keep tests conservative and lightweight.",
    ]

    return "\n".join(
        [
            f"run_id: {packet.run_id}",
            f"target_type: {target.target_type}",
            f"target_key: {target.target_key}",
            f"symbol: {target.symbol}",
            f"signature: {target.signature or 'unknown'}",
            f"file_path: {target.file_path}",
            f"line_range: {source.line_start}-{source.line_end}",
            f"framework_hints: {', '.join(target.framework_hints) if target.framework_hints else 'none'}",
            f"http_method: {target.http_method or 'n/a'}",
            f"route_path: {target.route_path or 'n/a'}",
            "",
            *test_instructions,
            "",
            "Source context:",
            source.code,
        ]
    )
