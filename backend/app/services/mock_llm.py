"""Mock LLM for offline development — returns deterministic responses."""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatResult, ChatGeneration


class MockChatModel(BaseChatModel):
    """A mock chat model that echoes back or returns canned responses.

    Used during M0-M1 to develop the full interview flow without API costs.
    """

    response_text: str = ""

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        **kwargs,
    ) -> ChatResult:
        # If a specific response was set, use it; otherwise echo the last message
        text = self.response_text or f"[Mock] 收到: {messages[-1].content[:100]}"
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    @property
    def _llm_type(self) -> str:
        return "mock-chat-model"
