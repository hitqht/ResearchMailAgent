"""Single bounded HTTP request, no redirects, proxies, tools, or fallback."""

import json
from dataclasses import dataclass
from typing import Protocol, cast

import httpx

from researchmail.llm.models import AIError, ModelConfig

MAX_RESPONSE = 1_000_000


class LLMProvider(Protocol):
    def complete(self, system: str, content: str, schema: dict[str, object]) -> str: ...


class HTTPProvider:
    def __init__(
        self,
        config: ModelConfig,
        secret: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config
        self._secret = secret
        self.transport = transport

    def _post(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        if self.config.auth != "none" and not self._secret:
            raise AIError("auth")
        headers = {"Content-Type": "application/json"}
        if self.config.auth == "bearer":
            headers["Authorization"] = "Bearer " + (self._secret or "")
        elif self.config.auth == "x-api-key":
            headers["x-api-key"] = self._secret or ""
        try:
            with (
                httpx.Client(
                    timeout=httpx.Timeout(90, connect=5),
                    follow_redirects=False,
                    trust_env=False,
                    transport=self.transport,
                ) as client,
                client.stream(
                    "POST", self.config.base_url.rstrip("/") + path, headers=headers, json=payload
                ) as response,
            ):
                if response.status_code in {401, 403}:
                    raise AIError("auth")
                if response.status_code != 200:
                    raise AIError("response")
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_RESPONSE:
                        raise AIError("response")
                value = json.loads(data)
                if not isinstance(value, dict):
                    raise AIError("response")
                return cast(dict[str, object], value)
        except httpx.TimeoutException:
            raise AIError("timeout") from None
        except httpx.HTTPError:
            raise AIError("network") from None
        except (ValueError, TypeError):
            raise AIError("response") from None


class OllamaProvider(HTTPProvider):
    def complete(self, system: str, content: str, schema: dict[str, object]) -> str:
        # Revalidate at the network boundary, including objects from injected factories.
        config = ModelConfig.model_validate(self.config.model_dump())
        if not config.local:
            raise AIError("privacy")
        details = self._post("/api/show", {"model": config.model})
        metadata = details.get("model_info")
        if (
            details.get("remote_host")
            or details.get("remote_model")
            or not isinstance(metadata, dict)
            or not metadata
        ):
            raise AIError("privacy")
        response = self._post(
            "/api/chat",
            {
                "model": config.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": content},
                ],
                "stream": False,
                "format": schema,
                "options": {"temperature": 0, "num_predict": 4096, "num_ctx": 8192},
            },
        )
        message = response.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise AIError("response")
        if response.get("done") is not True or message.get("tool_calls"):
            raise AIError("response")
        return cast(str, message["content"])


class OpenAICompatibleProvider(HTTPProvider):
    def complete(self, system: str, content: str, schema: dict[str, object]) -> str:
        response = self._post(
            "/chat/completions",
            {
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": content},
                ],
                "stream": False,
                "response_format": {"type": "json_object"},
            },
        )
        # Compatible JSON mode is only a transport aid; Pydantic validates all output.
        try:
            choice = cast(list[dict[str, object]], response["choices"])[0]
            message = cast(dict[str, object], choice["message"])
            if choice.get("finish_reason") != "stop" or message.get("tool_calls"):
                raise AIError("response")
            result = message["content"]
            if not isinstance(result, str):
                raise AIError("response")
            return result
        except (KeyError, IndexError, TypeError, AttributeError):
            raise AIError("response") from None


@dataclass
class MockProvider:
    response: str
    calls: int = 0

    def complete(self, system: str, content: str, schema: dict[str, object]) -> str:
        self.calls += 1
        return self.response
