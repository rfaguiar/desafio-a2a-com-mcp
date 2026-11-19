"""Parsing deterministico das mensagens publicas do agente."""

from __future__ import annotations

import re
from typing import Any

PADRAO_RESERVA = re.compile(
    r"^reservar sala=(\S+) inicio=(\S+) fim=(\S+) responsavel=(.+)$"
)


def texto_da_mensagem(mensagem: dict[str, Any]) -> str:
    partes = mensagem.get("parts")
    if not isinstance(partes, list) or not partes:
        raise ValueError("Mensagem deve conter ao menos uma parte de texto")
    textos = [parte.get("text") for parte in partes if isinstance(parte, dict)]
    if not textos or not all(isinstance(texto, str) for texto in textos):
        raise ValueError("Mensagem deve conter somente partes de texto")
    return " ".join(textos)


def parse_reserva(texto: str) -> dict[str, str]:
    correspondencia = PADRAO_RESERVA.fullmatch(texto)
    if correspondencia is None:
        raise ValueError("Formato de pedido de reserva invalido")
    sala, inicio, fim, responsavel = correspondencia.groups()
    if not responsavel.strip():
        raise ValueError("Responsavel nao pode ser vazio")
    return {
        "sala": sala,
        "inicio": inicio,
        "fim": fim,
        "responsavel": responsavel.strip(),
    }


def parse_escolha(texto: str) -> str:
    if not texto.startswith("escolha=") or "\n" in texto:
        raise ValueError("Formato de escolha invalido")
    escolha = texto.removeprefix("escolha=")
    if not escolha or any(caractere.isspace() for caractere in escolha):
        raise ValueError("Formato de escolha invalido")
    return escolha
