import time
from dataclasses import dataclass, field
from typing import Optional
from config import MODELS


@dataclass
class Message:
    role: str
    content: str
    model: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class Session:
    id: str
    started_at: float = field(default_factory=time.time)
    messages: list[Message] = field(default_factory=list)
    current_model: str = "qwen"
    total_tokens_in: int = 0
    total_tokens_out: int = 0

    def add_user_message(self, content: str):
        self.messages.append(Message(role="user", content=content))

    def add_assistant_message(self, content: str, model: str,
                               tokens_in: int = 0, tokens_out: int = 0):
        self.messages.append(Message(role="assistant", content=content,
                                      model=model, tokens_in=tokens_in,
                                      tokens_out=tokens_out))
        self.total_tokens_in += tokens_in
        self.total_tokens_out += tokens_out

    def get_history_for_llm(self, max_messages: int = 50) -> list[dict]:
        recent = self.messages[-max_messages:]
        return [{"role": m.role, "content": m.content} for m in recent]

    def get_total_cost(self) -> float:
        cost = 0.0
        for msg in self.messages:
            if msg.model and msg.model in MODELS:
                m = MODELS[msg.model]
                cost += (msg.tokens_in / 1_000_000) * m["cost_input_per_1m"]
                cost += (msg.tokens_out / 1_000_000) * m["cost_output_per_1m"]
        return round(cost, 4)


class SessionStore:
    def __init__(self):
        self.sessions: dict[str, Session] = {}

    def create(self, session_id: str) -> Session:
        session = Session(id=session_id)
        self.sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Optional[Session]:
        return self.sessions.get(session_id)

    def get_or_create(self, session_id: str) -> Session:
        if session_id not in self.sessions:
            return self.create(session_id)
        return self.sessions[session_id]

    def delete(self, session_id: str):
        self.sessions.pop(session_id, None)


store = SessionStore()
