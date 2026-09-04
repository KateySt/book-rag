from anthropic import AsyncAnthropic

from src.settings import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, ANTHROPIC_MAX_TOKEN

anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)


async def generate_answer(question: str, context: str) -> str:
    message = await anthropic_client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=ANTHROPIC_MAX_TOKEN,
        messages=[
            {
                "role": "user",
                "content": (
                    "Answer the question using ONLY the context below. "
                    "If the answer isn't in the context, say so.\n\n"
                    f"Context:\n{context}\n\nQuestion: {question}"
                ),
            }
        ],
    )
    return message.content[0].text
