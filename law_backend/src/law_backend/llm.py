"""CrewAI adapter for Chat Completions providers with differing JSON capabilities."""

import json

from crewai import BaseLLM
from pydantic import Field, PrivateAttr, ValidationError

from .providers import complete


class CompatibleLLM(BaseLLM):
    connection: dict = Field(exclude=True, repr=False)
    _usage: dict = PrivateAttr(default_factory=dict)

    def call(
        self,
        messages,
        tools=None,
        callbacks=None,
        available_functions=None,
        from_task=None,
        from_agent=None,
        response_model=None,
    ):
        if tools or available_functions:
            raise ValueError("此工作流只接受已取得的材料，不开放模型自主工具调用")
        messages = (
            [{"role": "user", "content": messages}]
            if isinstance(messages, str)
            else [dict(message) for message in messages]
        )
        if response_model:
            messages.append(
                {
                    "role": "user",
                    "content": "仅输出一个符合下列 JSON Schema 的 JSON 对象，不使用 Markdown 围栏，不输出推理过程。\n"
                    + json.dumps(response_model.model_json_schema(), ensure_ascii=False),
                }
            )
        try:
            answer, usage = complete(
                self.connection,
                messages,
                max_tokens=7000,
                json_mode=bool(response_model and self.connection.get("json_mode")),
            )
        except ValueError:
            raise ValueError("模型没有返回完整有效的内容，请缩小范围或检查模型配置") from None
        except Exception:
            raise RuntimeError("模型服务请求失败，请检查模型权限、额度和网络") from None
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            if isinstance(usage.get(key), int):
                self._usage[key] = self._usage.get(key, 0) + usage[key]
        if response_model:
            try:
                parsed = response_model.model_validate_json(answer)
            except ValidationError:
                raise ValueError("模型输出不符合任务结构，未保存为有效分析，请重新发起") from None
            return parsed.model_dump_json()
        return answer

    def supports_function_calling(self):
        return False

    def supports_stop_words(self):
        return False

    def get_context_window_size(self):
        # The application applies an explicit material limit and never silently summarizes evidence.
        return 131072

    def usage(self):
        return dict(self._usage)
