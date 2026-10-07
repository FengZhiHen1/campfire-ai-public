"""最小复现：Graphiti 的 OpenAIEmbedder 在 TokenHub 上能否构造出一次成功的嵌入调用。

背景：`modules/library/embedding.py` 的 docstring 记着同一类缺陷的**已修**实例——
OpenAI SDK 在未显式给 `encoding_format` 时填 `base64`，而 TokenHub 只接受 `float`
（实测错误码 400001）。记忆侧走的是 Graphiti 自己的 `OpenAIEmbedder`，本脚本查它是否
也漏了这个参数。

本脚本只调嵌入，不写图库、不调模型对话。
"""

from __future__ import annotations

import asyncio

from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from openai import AsyncOpenAI

from campfire.core.config import EMBEDDING_DIM, get_settings
from campfire.agent.model.proxy_env import normalized_no_proxy_environment


async def main() -> int:
    settings = get_settings()
    api_key = settings.tokenhub_api_key.get_secret_value()

    with normalized_no_proxy_environment():
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=settings.tokenhub_base_url,
            timeout=settings.model_request_timeout_seconds,
            max_retries=0,
        )
        embedder = OpenAIEmbedder(
            config=OpenAIEmbedderConfig(
                embedding_dim=EMBEDDING_DIM,
                embedding_model=settings.embedding_model_name,
                api_key=api_key,
                base_url=settings.tokenhub_base_url,
            ),
            client=client,
        )

        print("--- 1) 不带 encoding_format（Graphiti 的现状）---")
        try:
            vector = await embedder.create("T11 复现探针")
            print(f"OK dim={len(vector)}")
        except Exception as exc:  # noqa: BLE001 —— 探针要把失败原文打出来
            print(f"FAIL {type(exc).__name__}: {str(exc)[:300]}")

        print("--- 2) 带 encoding_format='float'（RAG 路径的做法）---")
        try:
            response = await client.embeddings.create(
                input=["T11 复现探针"],
                model=settings.embedding_model_name,
                encoding_format="float",
            )
            print(f"OK dim={len(response.data[0].embedding)}")
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {type(exc).__name__}: {str(exc)[:300]}")

        print("--- 3) 不带 encoding_format 的裸 SDK 调用（对照）---")
        try:
            response = await client.embeddings.create(input=["T11 复现探针"], model=settings.embedding_model_name)
            print(f"OK dim={len(response.data[0].embedding)}")
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {type(exc).__name__}: {str(exc)[:200]}")

        await client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
