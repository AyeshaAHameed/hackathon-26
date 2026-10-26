"""OpenRouter API client and grounded prompt construction."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from cnc_intelligence.config import SYSTEM_PROMPT, Settings, get_settings
from cnc_intelligence.models import AnswerStatus, PartRecord
from cnc_intelligence.question_router import RoutedQuestion

logger = logging.getLogger(__name__)


class LLMServiceError(Exception):
    """Raised when the OpenRouter call fails in a user-facing way."""

    def __init__(self, message: str, code: str = "llm_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def build_user_prompt(
    record: PartRecord,
    question: str,
    routed: RoutedQuestion | None = None,
) -> str:
    """Construct the grounded user prompt with only the selected record."""
    display = record.display_fields()
    lines = [
        f"Part number: {record.part_number}",
        f"Source filename: {record.source.filename}",
        f"Sheet: {record.source.sheet_name}",
        f"Part-number column: {record.source.part_number_column}",
        "",
        "Verified manufacturing record (original column names and values):",
    ]
    for col, val in display.items():
        lines.append(f"- {col}: {val}")

    lines.append("")
    lines.append(f"User question: {question}")

    if routed is not None:
        lines.append(f"Question category: {routed.category.value}")
        if routed.matched_columns:
            lines.append(
                "Relevant columns identified by the application: "
                + ", ".join(routed.matched_columns)
            )
        if routed.missing_topics:
            lines.append("Topics that appear unavailable: " + ", ".join(routed.missing_topics))

    lines.append("")
    lines.append(
        "Respond with a single JSON object only (no markdown fences) using keys: "
        "answer, status, evidence, missing_information, limitations."
    )
    return "\n".join(lines)


def _extract_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from model output, tolerating markdown fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Strip markdown code fence
        lines = cleaned.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
        raise LLMServiceError(
            "Model returned JSON that is not an object.",
            code="malformed_response",
        )
    except json.JSONDecodeError:
        # Attempt to locate first {...} block
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(cleaned[start : end + 1])
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass
        raise LLMServiceError(
            "Model returned malformed JSON that could not be parsed.",
            code="malformed_response",
        ) from None


class OpenRouterClient:
    """Production-conscious OpenRouter chat-completions client."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def ensure_configured(self) -> None:
        if not self.settings.api_key_configured:
            raise LLMServiceError(
                "AI service is not configured. Set the API key in your .env file.",
                code="missing_api_key",
            )
        if not self.settings.model_configured:
            raise LLMServiceError(
                "AI model is not configured. Set the model ID in your .env file.",
                code="missing_model",
            )

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "Content-Type": "application/json",
        }
        if self.settings.openrouter_site_url:
            headers["HTTP-Referer"] = self.settings.openrouter_site_url
        if self.settings.openrouter_app_name:
            headers["X-Title"] = self.settings.openrouter_app_name
        return headers

    def _build_payload(self, user_prompt: str, *, use_json_format: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.settings.openrouter_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.settings.llm_temperature,
            "max_tokens": self.settings.max_output_tokens,
        }
        if use_json_format:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.settings.openrouter_base_url.rstrip('/')}/chat/completions"
        timeout = httpx.Timeout(self.settings.request_timeout_seconds)
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(url, headers=self._headers(), json=payload)
        except httpx.TimeoutException as exc:
            raise LLMServiceError(
                "The AI request timed out. Try again or increase REQUEST_TIMEOUT_SECONDS.",
                code="timeout",
            ) from exc
        except httpx.NetworkError as exc:
            raise LLMServiceError(
                "Network failure while contacting the AI service. Check your connection.",
                code="network_error",
            ) from exc

        return self._handle_http_response(response)

    def _handle_http_response(self, response: httpx.Response) -> dict[str, Any]:
        status = response.status_code
        if status == 401:
            raise LLMServiceError(
                "The AI service rejected the API key (unauthorized).",
                code="invalid_api_key",
            )
        if status == 402:
            raise LLMServiceError(
                "The AI service reports insufficient credits for this request.",
                code="provider_error",
            )
        if status == 404:
            raise LLMServiceError(
                "The configured AI model was not found or is unavailable. "
                "Check the model ID in your .env file.",
                code="invalid_model",
            )
        if status == 429:
            raise LLMServiceError(
                "AI service rate limit exceeded. Wait briefly and try again.",
                code="rate_limit",
            )
        if status >= 500:
            raise LLMServiceError(
                "The AI service is temporarily unavailable (server error).",
                code="provider_error",
            )
        if status >= 400:
            # Avoid echoing response bodies that might contain sensitive details
            logger.warning("AI client error status=%s", status)
            raise LLMServiceError(
                f"The AI service returned an error (HTTP {status}). "
                "Verify your model ID and account settings.",
                code="provider_error",
            )

        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise LLMServiceError(
                "The AI service returned a non-JSON response.",
                code="malformed_response",
            ) from exc

    def _content_from_response(self, data: dict[str, Any]) -> str:
        choices = data.get("choices")
        if not choices or not isinstance(choices, list):
            raise LLMServiceError(
                "The AI service response contained no choices.",
                code="empty_response",
            )
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            raise LLMServiceError(
                "The AI service response was missing a message.",
                code="empty_response",
            )
        content = message.get("content")
        if content is None or (isinstance(content, str) and content.strip() == ""):
            raise LLMServiceError(
                "The model returned an empty response.",
                code="empty_response",
            )
        if not isinstance(content, str):
            # Some providers return structured content lists
            content = json.dumps(content)
        return content

    def complete_json(self, user_prompt: str) -> dict[str, Any]:
        """
        Call OpenRouter and return a parsed JSON object.

        Tries JSON response_format first; falls back without it if the model
        rejects the format parameter.
        """
        self.ensure_configured()
        use_json_format = True
        last_error: LLMServiceError | None = None
        attempts = max(1, self.settings.max_retries + 1)

        for attempt in range(attempts):
            payload = self._build_payload(user_prompt, use_json_format=use_json_format)
            try:
                data = self._post(payload)
                content = self._content_from_response(data)
                return _extract_json_object(content)
            except LLMServiceError as exc:
                last_error = exc
                # If JSON format unsupported, retry once without it
                if use_json_format and exc.code == "provider_error" and attempt == 0:
                    logger.info("Retrying without response_format=json_object after provider error")
                    use_json_format = False
                    continue
                # Retry transient failures with simple backoff
                if exc.code in {"rate_limit", "timeout", "network_error", "provider_error"}:
                    if attempt < attempts - 1:
                        time.sleep(0.5 * (2**attempt))
                        continue
                raise

        assert last_error is not None
        raise last_error

    def answer_question(
        self,
        record: PartRecord,
        question: str,
        routed: RoutedQuestion | None = None,
    ) -> dict[str, Any]:
        """Build a grounded prompt and return the raw structured LLM payload."""
        prompt = build_user_prompt(record, question, routed)
        return self.complete_json(prompt)


def direct_answer_payload(
    record: PartRecord,
    routed: RoutedQuestion,
) -> dict[str, Any]:
    """
    Build a structured answer payload without calling the LLM.

    Used for direct field lookups and out-of-scope responses.
    """
    evidence: list[dict[str, str]] = []
    for col in routed.matched_columns:
        display = record.display_fields().get(col)
        if display and display != "(not recorded)":
            evidence.append({"column": col, "value": display})

    if routed.category.value == "pdf_or_iges":
        status = AnswerStatus.UNSUPPORTED.value
    elif routed.category.value == "unrelated":
        status = AnswerStatus.UNSUPPORTED.value
    elif routed.missing_topics and not evidence:
        status = AnswerStatus.NOT_FOUND.value
    elif routed.missing_topics and evidence:
        status = AnswerStatus.PARTIALLY_ANSWERED.value
    else:
        status = AnswerStatus.ANSWERED.value

    limitations: list[str] = []
    if routed.category.value == "pdf_or_iges":
        limitations.append(
            "Level 1 analyzes Excel manufacturing records only; "
            "PDF and IGES sources are not processed."
        )

    return {
        "answer": routed.direct_answer_hint or routed.message,
        "status": status,
        "evidence": evidence,
        "missing_information": list(routed.missing_topics),
        "limitations": limitations,
    }
