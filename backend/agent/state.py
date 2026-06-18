from typing import TypedDict, Optional, List, Literal
from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    # Session context
    user_id: str
    session_id: str

    # Routing
    mode: Literal["diagnostic", "learn", "quiz", "reading", "feedback"]

    # Current study item
    current_word: Optional[str]
    current_passage: Optional[str]
    current_question: Optional[str]

    # User input
    user_text: Optional[str]       # typed input
    user_audio_b64: Optional[str]  # base64 audio from STT

    # Agent output
    agent_text: str
    agent_audio_b64: Optional[str]  # base64 TTS response
    hindi_translation: Optional[str]

    # Evaluation results
    is_correct: Optional[bool]
    feedback: Optional[str]
    mastery_delta: int              # +1 correct, -1 incorrect, 0 no change

    # Mastery updates to persist after turn
    mastery_updates: List[dict]     # [{word, new_level}]

    # Conversation history
    messages: List[BaseMessage]
