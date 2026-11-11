import json
import os
from openai import OpenAI
from providers.base import ModelReply, ToolCall, ConversationMessage, ToolSpec
from providers.errors import ProviderError, normalize_error, KNOWN_MODELS


def encode_message(message):
    if isinstance(message, dict):  # Legacy records/adapter clients, never emitted by new Runtime.
        return message
    data = {"role": message.role, "content": message.text or None}
    if message.calls:
        data["tool_calls"] = [{"id": c.id, "type": "function", "function": {
            "name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)}} for c in message.calls]
    if message.call_id:
        data.update(tool_call_id=message.call_id, content=json.dumps(message.result, ensure_ascii=False))
    return data


def encode_tool(tool):
    if isinstance(tool, dict):
        return tool
    return {"type": "function", "function": {"name": tool.name, "description": tool.description,
                                              "parameters": tool.parameters}}


def groq_client() -> OpenAI:
    from providers.local_settings import local_only, LocalAIError
    if local_only(): raise LocalAIError('cloud_disabled')
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        raise ValueError("Нет GROQ_API_KEY. Заполните файл .env.")
    return OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1", timeout=30, max_retries=0)


class GroqProvider:
    def __init__(self, client=None, model=None, budget=None):
        self.client = client
        self.model = model or os.getenv('GROQ_MODEL', 'openai/gpt-oss-20b')
        self.budget = budget
        self.request_count=0; self.retry_count=0; self.retry_diagnostics=[]

    def metadata(self):
        return {'provider':'Groq','model':self.model if self.model in KNOWN_MODELS else 'unrecognized_model',
            'operation':'agent','request_count':self.request_count,'retry_count':self.retry_count,
            'fallback':False,'retry_diagnostics':list(self.retry_diagnostics)}

    def complete(self, messages, tools):
        from providers.local_settings import local_only, LocalAIError
        if local_only(): raise LocalAIError('cloud_disabled')
        options = dict(model=self.model,
                       messages=[encode_message(m) for m in messages], temperature=0.2, max_completion_tokens=1800)
        if options["model"] in KNOWN_MODELS:
            options["reasoning_effort"] = "low"
        if tools:
            options.update(tools=[encode_tool(t) for t in tools], tool_choice="auto", parallel_tool_calls=False)
        names=[name for t in tools if (name:=encode_tool(t).get('function',{}).get('name'))]
        if self.client is None and not os.getenv('GROQ_API_KEY','').strip():
            raise ProviderError(self.model,'agent','authentication')
        for attempt in range(2):
            if self.budget: self.budget.consume()  # Every HTTP attempt, including the one permitted retry.
            self.request_count+=1
            if attempt: self.retry_count+=1
            try:
                if self.client is not None:
                    response = self.client.chat.completions.create(**options)
                else:
                    with groq_client() as client:
                        response = client.chat.completions.create(**options)
                message = response.choices[0].message
                calls = [ToolCall(call.id, call.function.name, json.loads(call.function.arguments))
                         for call in (message.tool_calls or [])]
                if any(not isinstance(c.arguments,dict) for c in calls):
                    raise ProviderError(self.model,'agent','tool_generation_failed',retryable=True,
                                        diagnostics={'generation_reason':'invalid_tool_arguments_json'})
                return ModelReply(message.content or "", calls)
            except Exception as exc:
                error=(ProviderError(self.model,'agent','tool_generation_failed',retryable=True,
                    diagnostics={'generation_reason':'invalid_tool_arguments_json'}) if isinstance(exc,json.JSONDecodeError)
                    else normalize_error(exc,self.model,'agent',names))
                error.request_count=self.request_count; error.retry_count=self.retry_count
                if not (error.retryable and names and attempt==0): raise error from None
                self.retry_diagnostics.append(error.public())
                options['temperature']=0
