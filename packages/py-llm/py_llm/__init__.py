"""py-llm: LLM API client package for Campfire-AI.

Provides unified LLM client interface for streaming chat completion
via DeepSeek API (OpenAI-compatible protocol).
"""

from py_llm.client import ChatCompletionChunk, Choice, Delta, LLMClient

__all__ = [
    "LLMClient",
    "ChatCompletionChunk",
    "Choice",
    "Delta",
]
