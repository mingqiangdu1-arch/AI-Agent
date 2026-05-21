"""LLM 服务模块。

统一管理 LLM 调用、Prompt 模板加载和响应解析。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib import error, request

from src.core.config import LLMConfig, get_config
from src.core.exceptions import ConfigError, LLMError
from src.core.models import LLMEnhanceResult, LLMResult, LLMTuningResult


class LLMService:
    """LLM 调用服务。"""

    PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

    def __init__(self, config: LLMConfig | None = None) -> None:
        self._config = config or get_config().llm

    @property
    def config(self) -> LLMConfig:
        return self._config

    def update_config(self, config: LLMConfig) -> None:
        self._config = config

    def is_configured(self) -> bool:
        return self._config.is_configured

    def resolve_config(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMConfig:
        """解析 LLM 配置，优先使用传入参数，否则使用环境变量。"""
        config = get_config().llm
        resolved = config.with_overrides(
            base_url=base_url,
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if not resolved.is_configured:
            missing = []
            if not resolved.base_url:
                missing.append("LLM_BASE_URL")
            if not resolved.api_key:
                missing.append("LLM_API_KEY")
            if not resolved.model:
                missing.append("LLM_MODEL")
            raise ConfigError(f"LLM 配置不完整，缺少: {', '.join(missing)}")
        return resolved

    def call(self, messages: list[dict[str, str]], config: LLMConfig | None = None) -> str:
        """调用 LLM 接口，返回响应文本。"""
        cfg = config or self._config
        if not cfg.is_configured:
            raise ConfigError("LLM 未配置")

        endpoint = self._resolve_chat_endpoint(cfg.base_url)
        payload = {
            "model": cfg.model,
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
            "messages": messages,
        }

        req = request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {cfg.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=45) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            return str(data["choices"][0]["message"]["content"]).strip()
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
            raise LLMError(f"LLM 调用失败: HTTP {exc.code} {detail[:240]}") from exc
        except error.URLError as exc:
            raise LLMError(f"LLM 接口不可达: {exc.reason}") from exc
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise LLMError("LLM 返回格式异常") from exc

    def call_json(self, messages: list[dict[str, str]], config: LLMConfig | None = None) -> dict[str, Any]:
        """调用 LLM 并解析 JSON 响应。"""
        cfg = config or self._config
        endpoint = self._resolve_chat_endpoint(cfg.base_url)
        payload = {
            "model": cfg.model,
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
            "response_format": {"type": "json_object"},
            "messages": messages,
        }

        req = request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {cfg.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=45) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            content = str(data["choices"][0]["message"]["content"]).strip()
            return self._parse_json_object(content)
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
            raise LLMError(f"LLM 调用失败: HTTP {exc.code} {detail[:240]}") from exc
        except error.URLError as exc:
            raise LLMError(f"LLM 接口不可达: {exc.reason}") from exc
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise LLMError("LLM 返回格式异常") from exc

    def test_connection(self, config: LLMConfig | None = None) -> tuple[bool, str]:
        """测试 LLM 连通性。"""
        cfg = config or self._config
        if not cfg.is_configured:
            return False, "LLM 未配置"

        try:
            self.call(
                [
                    {"role": "system", "content": "你是API连通性检测助手。"},
                    {"role": "user", "content": "回复: ok"},
                ],
                config=cfg,
            )
            return True, f"连接成功: {cfg.base_url}"
        except Exception as exc:
            return False, str(exc)

    def load_prompt_template(self, prompt_name: str) -> tuple[str, str]:
        """加载 Prompt 模板，返回 (system_prompt, user_prompt)。"""
        prompt_path = self.PROMPTS_DIR / f"{prompt_name}.txt"
        if not prompt_path.exists():
            raise LLMError(f"Prompt 模板不存在: {prompt_name}")

        template_text = prompt_path.read_text(encoding="utf-8")
        return self._split_prompt_sections(template_text)

    def call_with_prompt(
        self,
        prompt_name: str,
        payload: dict[str, Any],
        config: LLMConfig | None = None,
    ) -> dict[str, Any]:
        """使用模板调用 LLM 并返回 JSON。"""
        system_prompt, user_prompt = self.load_prompt_template(prompt_name)
        payload_json = json.dumps(payload, ensure_ascii=False)
        user_prompt = user_prompt.replace("{{payload_json}}", payload_json)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return self.call_json(messages, config)

    @staticmethod
    def _resolve_chat_endpoint(base_url: str) -> str:
        cleaned = base_url.strip().rstrip("/")
        if cleaned.endswith("/chat/completions"):
            return cleaned
        if cleaned.endswith("/openai"):
            return f"{cleaned}/chat/completions"
        if re.search(r"/v\d+$", cleaned):
            return f"{cleaned}/chat/completions"
        return f"{cleaned}/v1/chat/completions"

    @staticmethod
    def _split_prompt_sections(template_text: str) -> tuple[str, str]:
        try:
            system_part = template_text.split("[SYSTEM]", 1)[1].split("[/SYSTEM]", 1)[0].strip()
            user_part = template_text.split("[USER]", 1)[1].split("[/USER]", 1)[0].strip()
        except (IndexError, ValueError) as exc:
            raise LLMError("Prompt 模板格式无效") from exc
        return system_part, user_part

    @staticmethod
    def _parse_json_object(raw_text: str) -> dict[str, Any]:
        text = raw_text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
            if text.endswith("```"):
                text = text[:-3].strip()

        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                data = json.loads(match.group(0))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {}


# 全局 LLM 服务实例
_llm_service: LLMService | None = None


def get_llm_service() -> LLMService:
    """获取全局 LLM 服务实例。"""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
