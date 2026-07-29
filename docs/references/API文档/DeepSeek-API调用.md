# DeepSeek API 调用规范

## 1. 基础接入

### 1.1 服务端点

| 协议 | 端点 |
|:---|:---|
| OpenAI 兼容格式 | `https://api.deepseek.com` |
| Anthropic 兼容格式 | `https://api.deepseek.com/anthropic` |

### 1.2 认证

所有请求需在 HTTP Header 中携带 API Key：

```http
Authorization: Bearer <DEEPSEEK_API_KEY>
Content-Type: application/json
```

**获取方式**：访问 [platform.deepseek.com](https://platform.deepseek.com) 注册并创建 API Key。新账户可获得 500 万免费 token 。

---

## 2. 模型规格

### 2.1 可用模型

| 模型 ID | 类型 | 上下文窗口 | 最大输出 | 弃用日期 | 备注 |
|:---|:---|:---|:---|:---|:---|
| `deepseek-v4-pro` | 旗舰 / 推理 | 1M tokens | 384K tokens | — | 支持思考模式 |
| `deepseek-v4-flash` | 轻量 / 高速 | 1M tokens | 384K tokens | — | 支持思考模式 |
| `deepseek-chat` | 兼容别名 | 1M tokens | 384K tokens | **2026-07-24** | 指向 V4-Flash 非思考模式 |
| `deepseek-reasoner` | 兼容别名 | 1M tokens | 384K tokens | **2026-07-24** | 指向 V4-Flash 思考模式 |

> **重要**：`deepseek-chat` 与 `deepseek-reasoner` 将于 **2026-07-24 15:59 UTC** 停止服务。新集成应直接使用 `deepseek-v4-pro` 或 `deepseek-v4-flash` 。

### 2.2 模式说明

- **非思考模式**：标准对话生成，响应快，成本低。
- **思考模式**：模型先输出推理过程（思维链），再给出最终答案。适合数学、逻辑、复杂分析任务。通过 `thinking` 参数启用（见第 5 节）。

---

## 3. 请求参数

### 3.1 完整参数表

| 参数 | 类型 | 必填 | 默认值 | 范围 | 说明 |
|:---|:---|:---|:---|:---|:---|
| `model` | string | **是** | — | 见 2.1 | 指定模型 ID |
| `messages` | array | **是** | — | 至少 1 条 | 对话消息列表 |
| `max_tokens` | integer | 否 | 4096 | 1 ~ 384000 | 最大生成 token 数 |
| `temperature` | float | 否 | 1.0 | 0.0 ~ 2.0 | 采样温度，控制随机性 |
| `top_p` | float | 否 | 1.0 | 0.0 ~ 1.0 | 核采样概率阈值 |
| `top_k` | integer | 否 | — | — | 候选 token 数量限制 |
| `frequency_penalty` | float | 否 | 0 | -2.0 ~ 2.0 | 重复内容惩罚 |
| `presence_penalty` | float | 否 | 0 | -2.0 ~ 2.0 | 新话题引入惩罚 |
| `stop` | string / array | 否 | null | 最多 4 个序列 | 停止生成标记 |
| `stream` | boolean | 否 | false | `true` / `false` | 是否流式输出 |
| `response_format` | object | 否 | `{"type":"text"}` | `text` / `json_object` | 强制输出格式 |
| `tools` | array | 否 | null | 函数定义数组 | 可用工具列表 |
| `tool_choice` | string / object | 否 | `"none"` | `"none"` / `"auto"` / `"any"` | 工具调用策略 |
| `logprobs` | boolean | 否 | false | `true` / `false` | 是否返回 token 对数概率 |
| `top_logprobs` | integer | 否 | — | 0 ~ 20 | 返回概率最高的 N 个 token |
| `thinking` | object | 否 | — | `{"type": "enabled"}` | 启用思考模式 |
| `reasoning_effort` | string | 否 | — | `"high"` / `"max"` | 思考强度（思考模式下有效） |

### 3.2 messages 结构

每条消息对象包含以下字段：

```json
{
  "role": "system" | "user" | "assistant" | "tool",
  "content": "string",
  "name": "string"           // 可选，用于区分同一角色的不同实例
}
```

**角色说明**：
- `system`：设置对话上下文与行为指令
- `user`：用户输入
- `assistant`：模型历史回复
- `tool`：工具调用结果回传（需配合 `tool_call_id`）

### 3.3 请求示例

```json
{
  "model": "deepseek-v4-pro",
  "messages": [
    {
      "role": "system",
      "content": "You are a helpful assistant."
    },
    {
      "role": "user",
      "content": "Hello!"
    }
  ],
  "temperature": 0.7,
  "max_tokens": 2048,
  "stream": false
}
```

---

## 4. 响应格式

### 4.1 标准响应（非流式）

```json
{
  "id": "chatcmpl-xxxxxxxx",
  "object": "chat.completion",
  "created": 1712345678,
  "model": "deepseek-v4-pro",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Hello! How can I help you today?",
        "tool_calls": null
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 12,
    "completion_tokens": 9,
    "total_tokens": 21
  }
}
```

### 4.2 思考模式响应

启用 `thinking: {"type": "enabled"}` 后，响应额外包含 `reasoning_content`：

```json
{
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "最终答案...",
        "reasoning_content": "推理过程...",
        "tool_calls": null
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 20,
    "completion_tokens": 500,
    "completion_tokens_details": {
      "reasoning_tokens": 400
    },
    "total_tokens": 520
  }
}
```

> **注意**：多轮对话中，前一轮的 `reasoning_content` **不会**自动进入下一轮上下文。若需保留推理历史，需在系统层手动注入 。

### 4.3 工具调用响应

当模型决定调用工具时，`message` 字段包含 `tool_calls`：

```json
{
  "message": {
    "role": "assistant",
    "content": null,
    "tool_calls": [
      {
        "id": "call_xxxxxxxx",
        "type": "function",
        "function": {
          "name": "get_weather",
          "arguments": "{\"city\":\"Beijing\",\"unit\":\"celsius\"}"
        }
      }
    ]
  },
  "finish_reason": "tool_calls"
}
```

---

## 5. 思考模式（Thinking Mode）

### 5.1 启用方式

**新接口（推荐）**：任意 V4 模型 + `thinking` 参数

```json
{
  "model": "deepseek-v4-pro",
  "thinking": {"type": "enabled"},
  "reasoning_effort": "high"
}
```

**旧接口（兼容，2026-07-24 弃用）**：直接使用 `deepseek-reasoner`

```json
{
  "model": "deepseek-reasoner"
}
```

### 5.2 思考模式下的参数约束

以下参数在思考模式下**设置不报错，但无实际效果** ：

- `temperature`
- `top_p`
- `presence_penalty`
- `frequency_penalty`

以下参数在思考模式下**会触发错误**：

- `logprobs`
- `top_logprobs`

### 5.3 推理努力程度

| 级别 | 说明 |
|:---|:---|
| `"high"` | 标准深度推理 |
| `"max"` | 最大深度推理，适合复杂 Agent 任务 |

---

## 6. 流式输出（SSE）

设置 `stream: true` 后，API 通过 Server-Sent Events 逐块返回内容。

### 6.1 响应格式

```http
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"delta":{"content":"Hello"},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"delta":{"content":"!"},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"delta":{"content":""},"finish_reason":"stop"}]}

data: [DONE]
```

### 6.2 思考模式流式输出

思考模式的流式输出同样通过 SSE 返回，`delta` 中可能包含 `reasoning_content` 字段。建议客户端将 `reasoning_content` 折叠显示，仅向用户展示 `content` 内容。

---

## 7. 工具调用（Function Calling）

### 7.1 工具定义

```json
{
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "获取指定城市的天气信息",
        "parameters": {
          "type": "object",
          "properties": {
            "city": {
              "type": "string",
              "description": "城市名称"
            },
            "unit": {
              "type": "string",
              "enum": ["celsius", "fahrenheit"]
            }
          },
          "required": ["city"]
        }
      }
    }
  ],
  "tool_choice": "auto"
}
```

### 7.2 工具结果回传

工具执行完成后，将结果以 `role: tool` 的消息回传：

```json
{
  "role": "tool",
  "tool_call_id": "call_xxxxxxxx",
  "content": "{\"temperature\": 22, \"condition\": \"sunny\"}"
}
```

---

## 8. 错误码

| HTTP 状态码 | 错误类型 | 说明 | 建议处理 |
|:---|:---|:---|:---|
| **400** | 格式错误 | 请求体 JSON 格式非法或参数类型错误 | 检查请求构造 |
| **401** | 认证失败 | API Key 错误或已过期 | 校验密钥有效性 |
| **402** | 余额不足 | 账户余额耗尽 | 充值或切换备用方案 |
| **422** | 参数错误 | 字段值非法或超出范围 | 根据错误提示修正参数 |
| **429** | 速率限制 | 请求过快或系统高负载 | 指数退避重试 |
| **500** | 服务器故障 | 内部错误 | 指数退避重试 |
| **503** | 服务繁忙 | 服务器过载 | 指数退避重试，或切换备用模型 |

> DeepSeek API 不限制用户并发量，但在系统总负载较高时会动态限流，可能导致 429 或 503 。

---

## 9. 定价

### 9.1 官方定价（2026-04）

| 计费项 | deepseek-v4-flash | deepseek-v4-pro |
|:---|:---|:---|
| 输入（Cache Miss） | ¥1.0 / 百万 tokens | ¥4.0 / 百万 tokens |
| 输入（Cache Hit） | ¥0.2 / 百万 tokens | ¥0.33 / 百万 tokens |
| 输出（标准模式） | ¥2.0 / 百万 tokens | ¥16.0 / 百万 tokens |
| 输出（思考模式） | — | ¥64.0 / 百万 tokens |
| 上下文窗口 | 1M tokens | 1M tokens |
| 最大输出 | 384K tokens | 384K tokens |

### 9.2 上下文缓存

DeepSeek 支持**自动上下文缓存**，无需修改代码即可生效 ：

- **命中条件**：请求前缀至少 1,024 tokens，且与历史请求字节级完全匹配
- **生效场景**：相同系统提示、共享对话历史、批量相似请求
- **优化建议**：将静态内容（系统提示、固定指令）放在消息列表前面，可变内容放在后面

---

## 10. OpenAI SDK 调用示例

### 10.1 安装

```bash
pip install openai
```

### 10.2 基础调用

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-your-api-key",
    base_url="https://api.deepseek.com"
)

response = client.chat.completions.create(
    model="deepseek-v4-pro",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"}
    ],
    temperature=0.7,
    max_tokens=2048
)

print(response.choices[0].message.content)
```

### 10.3 流式输出

```python
stream = client.chat.completions.create(
    model="deepseek-v4-pro",
    messages=[
        {"role": "user", "content": "Write a short story about space exploration."}
    ],
    stream=True
)

for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

### 10.4 思考模式

```python
response = client.chat.completions.create(
    model="deepseek-v4-pro",
    messages=[
        {"role": "user", "content": "Prove that the square root of 2 is irrational."}
    ],
    thinking={"type": "enabled"},
    reasoning_effort="high"
)

# 推理过程
print("Reasoning:", response.choices[0].message.reasoning_content)

# 最终答案
print("Answer:", response.choices[0].message.content)
```

### 10.5 JSON 模式输出

```python
response = client.chat.completions.create(
    model="deepseek-v4-pro",
    messages=[
        {"role": "system", "content": "You are a helpful assistant. Always respond in valid JSON."},
        {"role": "user", "content": "List three colors and their hex codes."}
    ],
    response_format={"type": "json_object"},
    temperature=0.3
)

import json
result = json.loads(response.choices[0].message.content)
```

### 10.6 工具调用

```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取指定城市的天气信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名称"},
                    "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]}
                },
                "required": ["city"]
            }
        }
    }
]

response = client.chat.completions.create(
    model="deepseek-v4-pro",
    messages=[{"role": "user", "content": "北京今天天气怎么样？"}],
    tools=tools,
    tool_choice="auto"
)

tool_call = response.choices[0].message.tool_calls[0]
print(f"调用函数: {tool_call.function.name}")
print(f"参数: {tool_call.function.arguments}")
```

### 10.7 异步调用

```python
from openai import AsyncOpenAI

client = AsyncOpenAI(
    api_key="sk-your-api-key",
    base_url="https://api.deepseek.com"
)

async def chat():
    response = await client.chat.completions.create(
        model="deepseek-v4-pro",
        messages=[{"role": "user", "content": "Hello!"}]
    )
    return response.choices[0].message.content
```

### 10.8 带重试的健壮调用

```python
import time
import random
from openai import RateLimitError, APIStatusError, APITimeoutError

def call_with_retry(client, messages, max_retries=3, base_delay=3, max_delay=120, **kwargs):
    for attempt in range(max_retries + 1):
        try:
            return client.chat.completions.create(
                model=kwargs.get("model", "deepseek-v4-pro"),
                messages=messages,
                timeout=90,
                **kwargs
            )
        except (RateLimitError, APITimeoutError, APIStatusError) as exc:
            if attempt == max_retries:
                raise
            delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
            time.sleep(delay)
```

---

## 11. 版本兼容与迁移

| 时间节点 | 事项 |
|:---|:---|
| **2026-04-24** | V4 系列正式发布，`deepseek-chat` / `deepseek-reasoner` 开始映射到 V4-Flash |
| **2026-07-24 15:59 UTC** | `deepseek-chat` 与 `deepseek-reasoner` 彻底停止服务 |
| **当前** | 新代码应直接使用 `deepseek-v4-pro` 或 `deepseek-v4-flash` |

**从 OpenAI 迁移**：仅需修改两行代码——`base_url` 改为 `https://api.deepseek.com`，`model` 改为 DeepSeek 模型 ID。消息格式、流式输出、工具调用、JSON 模式等行为完全一致 。

---

## 12. 参考链接

- [DeepSeek API 官方文档](https://api-docs.deepseek.com/zh-cn/) 
- [创建 Chat Completion](https://api-docs.deepseek.com/api/create-chat-completion) 
- [思考模式指南](https://api-docs.deepseek.com/guides/thinking_mode) 
- [错误码说明](https://api-docs.deepseek.com/quick_start/error_codes) 
- [定价与计费](https://api-docs.deepseek.com/quick_start/pricing) 
- [平台控制台](https://platform.deepseek.com) 