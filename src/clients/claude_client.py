from string import Template

from anthropic import AsyncAnthropic


class ClaudeClient:
    def __init__(self, *, api_key: str, model: str, max_tokens: int, answer_prompt: Template) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._answer_prompt = answer_prompt

    async def generate_answer(self, question: str, context: str) -> str:
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=[{"role": "user", "content": self._answer_prompt.substitute(context=context, question=question)}],
        )
        return message.content[0].text

    async def close(self) -> None:
        await self._client.close()
