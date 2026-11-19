"""Estado publico e privado das Tasks A2A."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import Any

ESTADOS_TERMINAIS = {
    "TASK_STATE_COMPLETED",
    "TASK_STATE_CANCELED",
    "TASK_STATE_FAILED",
}


def novo_id(prefixo: str) -> str:
    return f"{prefixo}-{secrets.token_hex(6)}"


def nova_mensagem(
    task_id: str,
    context_id: str,
    papel: str,
    texto: str,
) -> dict[str, Any]:
    return {
        "messageId": novo_id("msg"),
        "role": papel,
        "parts": [{"text": texto}],
        "taskId": task_id,
        "contextId": context_id,
    }


@dataclass
class EstadoPrivadoTask:
    traceparent: str | None = None
    argumentos_originais: dict[str, Any] | None = None
    input_key: str | None = None
    alternativas: list[str] = field(default_factory=list)
    request_state: str | None = None


@dataclass
class Task:
    id: str
    context_id: str
    state: str
    history: list[dict[str, Any]]
    status_message: dict[str, Any] | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    private: EstadoPrivadoTask = field(default_factory=EstadoPrivadoTask)
    transitions: list[str] = field(default_factory=list)

    @property
    def terminal(self) -> bool:
        return self.state in ESTADOS_TERMINAIS

    def transicionar(
        self, state: str, texto: str | None = None
    ) -> None:
        self.state = state
        self.transitions.append(state)
        if texto is None:
            return
        self.status_message = nova_mensagem(
            self.id, self.context_id, "ROLE_AGENT", texto
        )
        self.history.append(self.status_message)

    def como_publica(self) -> dict[str, Any]:
        status: dict[str, Any] = {"state": self.state}
        if self.status_message is not None:
            status["message"] = self.status_message
        return {
            "id": self.id,
            "contextId": self.context_id,
            "status": status,
            "history": self.history,
            "artifacts": self.artifacts,
        }


class Tarefas:
    def __init__(self) -> None:
        self._por_id: dict[str, Task] = {}

    def criar(
        self,
        mensagem: dict[str, Any],
        traceparent: str | None,
    ) -> Task:
        task = Task(
            id=novo_id("task"),
            context_id=novo_id("ctx"),
            state="TASK_STATE_SUBMITTED",
            history=[mensagem],
            private=EstadoPrivadoTask(traceparent=traceparent),
            transitions=["TASK_STATE_SUBMITTED"],
        )
        self._por_id[task.id] = task
        return task

    def obter(self, task_id: str) -> Task | None:
        return self._por_id.get(task_id)
