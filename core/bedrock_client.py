"""
bedrock_client.py
Amazon Bedrock LLM 統一呼叫模組

提供與原本 Ollama 對等的介面：
  - chat()          → 一般呼叫（同步，回傳完整回覆）
  - chat_stream()   → 串流呼叫（generator，逐 token 產出）
  - chat_json()     → JSON 模式呼叫（強制回傳 JSON）

支援模型：Claude 3.5 Sonnet / Claude 3 Haiku（透過 config 設定）
"""

import json
import boto3
from botocore.config import Config as BotoConfig

import config

# ── Bedrock Runtime Client（延遲初始化）────────────────
_bedrock_client = None


def _get_client():
    """取得或建立 Bedrock Runtime client（singleton）"""
    global _bedrock_client
    if _bedrock_client is None:
        boto_config = BotoConfig(
            region_name=config.AWS_REGION,
            retries={"max_attempts": 3, "mode": "adaptive"},
        )
        _bedrock_client = boto3.client(
            "bedrock-runtime",
            config=boto_config,
        )
        print(f"✅ [Bedrock] 已連線 AWS Bedrock（區域：{config.AWS_REGION}，模型：{config.BEDROCK_MODEL_ID}）")
    return _bedrock_client


def _build_messages(system: str = None, messages: list = None, user_text: str = None) -> tuple:
    """
    統一組裝 Bedrock Converse API 的 messages 格式。
    回傳 (system_prompt_list, messages_list)
    """
    system_prompts = []
    if system:
        system_prompts = [{"text": system}]

    if messages:
        # 轉換 OpenAI/Ollama 格式 → Bedrock Converse 格式
        bedrock_messages = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if role == "system":
                system_prompts.append({"text": content})
            else:
                bedrock_messages.append({
                    "role": role if role in ("user", "assistant") else "user",
                    "content": [{"text": content}],
                })
        return system_prompts, bedrock_messages

    if user_text:
        return system_prompts, [{"role": "user", "content": [{"text": user_text}]}]

    return system_prompts, []


def chat(system: str = None, messages: list = None, user_text: str = None,
         temperature: float = 0.0, max_tokens: int = 1024, model_id: str = None) -> str:
    """
    一般（非串流）呼叫 Bedrock，回傳完整文字回覆。

    用法：
        reply = bedrock_client.chat(system="你是...", user_text="你好")
        reply = bedrock_client.chat(messages=[{"role":"user","content":"你好"}])
    """
    client = _get_client()
    model = model_id or config.BEDROCK_MODEL_ID
    system_prompts, bedrock_messages = _build_messages(system, messages, user_text)

    if not bedrock_messages:
        return ""

    kwargs = {
        "modelId": model,
        "messages": bedrock_messages,
        "inferenceConfig": {
            "temperature": temperature,
            "maxTokens": max_tokens,
        },
    }
    if system_prompts:
        kwargs["system"] = system_prompts

    try:
        response = client.converse(**kwargs)
        output = response["output"]["message"]["content"]
        return output[0]["text"] if output else ""
    except Exception as e:
        print(f"🚨 [Bedrock] chat 錯誤：{e}")
        return ""


def chat_stream(system: str = None, messages: list = None, user_text: str = None,
                temperature: float = 0.0, max_tokens: int = 1024, model_id: str = None):
    """
    串流呼叫 Bedrock，逐 token yield 文字。

    用法：
        for token in bedrock_client.chat_stream(system="...", user_text="你好"):
            print(token, end="")
    """
    client = _get_client()
    model = model_id or config.BEDROCK_MODEL_ID
    system_prompts, bedrock_messages = _build_messages(system, messages, user_text)

    if not bedrock_messages:
        return

    kwargs = {
        "modelId": model,
        "messages": bedrock_messages,
        "inferenceConfig": {
            "temperature": temperature,
            "maxTokens": max_tokens,
        },
    }
    if system_prompts:
        kwargs["system"] = system_prompts

    try:
        response = client.converse_stream(**kwargs)
        stream = response.get("stream")
        if not stream:
            return

        for event in stream:
            if "contentBlockDelta" in event:
                delta = event["contentBlockDelta"].get("delta", {})
                text = delta.get("text", "")
                if text:
                    yield text

    except Exception as e:
        print(f"🚨 [Bedrock] chat_stream 錯誤：{e}")


def chat_json(system: str = None, messages: list = None, user_text: str = None,
              temperature: float = 0.0, max_tokens: int = 1024, model_id: str = None) -> dict:
    """
    JSON 模式呼叫：強制 LLM 回傳 JSON。
    內部會在 system prompt 後追加 JSON 指示，並嘗試解析回傳值。

    用法：
        result = bedrock_client.chat_json(system="...", user_text="分析以下文字...")
    """
    json_instruction = "\n\n【輸出格式】你必須只輸出一個合法的 JSON 物件，不加任何其他文字、不加 markdown 標記。"

    effective_system = (system or "") + json_instruction

    raw = chat(
        system=effective_system,
        messages=messages,
        user_text=user_text,
        temperature=temperature,
        max_tokens=max_tokens,
        model_id=model_id,
    )

    if not raw:
        return {}

    # 嘗試解析 JSON
    try:
        clean = raw.strip()
        # 移除可能的 markdown 包裝
        if "```" in clean:
            parts = clean.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("{"):
                    clean = part
                    break
        # 提取 JSON 物件
        if "{" in clean:
            start = clean.index("{")
            end = clean.rindex("}") + 1
            clean = clean[start:end]
        return json.loads(clean)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"⚠️ [Bedrock] JSON 解析失敗：{e}\n原始回覆：{raw[:200]}")
        return {}
