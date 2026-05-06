from dataclasses import dataclass

from shared.config import AnalyzeConfig


SYSTEM_PROMPT = """You analyze software test execution results for a testing platform.

Rules:
- explain only from the provided evidence
- do not invent failures, vulnerabilities, or root causes
- distinguish baseline repository failures from generated test failures
- mention infrastructure/setup issues explicitly when present
- keep the output concise and practical
- output markdown only
"""


@dataclass(slots=True)
class OpenAIAnalyzeProvider:
    api_key: str
    config: AnalyzeConfig

    def generate_summary(self, evidence_packet: dict) -> str:
        return self._request(build_analyze_prompt(evidence_packet))

    def _request(self, user_prompt: str) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        response = client.chat.completions.create(
            model=self.config.model,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError("OpenAI response did not include message content")
        return content.strip()


def build_analyze_prompt(evidence_packet: dict) -> str:
    return "\n".join(
        [
            "Summarize this run in concise markdown for an engineer reviewing the results.",
            "Use these sections exactly: `# Run Analysis`, `## Overall`, `## Highest-Signal Findings`, `## Next Steps`.",
            "If there are no meaningful generated findings, say that directly.",
            "Do not claim certainty beyond the evidence packet.",
            "",
            "Evidence packet:",
            str(evidence_packet),
        ]
    )
