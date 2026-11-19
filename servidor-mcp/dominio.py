"""Modelos e carregamento do dominio de reservas."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

ERRO_JANELA = "Fora da janela de uso: a politica permite reservas entre 08:00 e 20:00"
ERRO_DURACAO = "Duracao acima do limite: a politica permite no maximo 2 horas"
ERRO_INTERVALO = "Intervalo invalido: fim deve ser posterior a inicio"

FUSO_SAO_PAULO = timezone(timedelta(hours=-3))
HORARIO_INICIAL = time(8)
HORARIO_FINAL = time(20)
DURACAO_MAXIMA = timedelta(hours=2)


class ErroDominio(ValueError):
    """Violacao deterministica da politica do dominio."""


@dataclass(frozen=True)
class Sala:
    id: str
    nome: str
    capacidade: int
    recursos: tuple[str, ...]


@dataclass(frozen=True)
class Reserva:
    id: str
    sala: str
    inicio: str
    fim: str
    responsavel: str


@dataclass(frozen=True)
class Politica:
    versao: str
    texto: str


@dataclass(frozen=True)
class Dominio:
    salas: tuple[Sala, ...]
    reservas: tuple[Reserva, ...]
    politica: Politica


def validar_sala(sala_id: str, salas: Sequence[Sala]) -> Sala:
    """Encontra uma sala ou falha com a mensagem publica do dominio."""
    for sala in salas:
        if sala.id == sala_id:
            return sala
    raise ErroDominio(f"Sala inexistente: {sala_id}")


def _interpretar_instante(valor: str) -> datetime:
    try:
        iso8601 = f"{valor[:-1]}+00:00" if valor.endswith(("Z", "z")) else valor
        instante = datetime.fromisoformat(iso8601)
    except (TypeError, ValueError) as erro:
        raise ErroDominio(ERRO_INTERVALO) from erro
    if instante.tzinfo is None:
        raise ErroDominio(ERRO_INTERVALO)
    return instante


def validar_janela(inicio: datetime, fim: datetime) -> None:
    """Valida os dois lados do intervalo na janela de Sao Paulo."""
    inicio_local = inicio.astimezone(FUSO_SAO_PAULO)
    fim_local = fim.astimezone(FUSO_SAO_PAULO)
    if (
        inicio_local.date() != fim_local.date()
        or inicio_local.time() < HORARIO_INICIAL
        or fim_local.time() > HORARIO_FINAL
    ):
        raise ErroDominio(ERRO_JANELA)


def validar_duracao(inicio: datetime, fim: datetime) -> None:
    """Valida a duracao maxima do intervalo."""
    if fim - inicio > DURACAO_MAXIMA:
        raise ErroDominio(ERRO_DURACAO)


def validar_intervalo(inicio: str, fim: str) -> tuple[datetime, datetime]:
    """Valida a ordem, a janela local e a duracao maxima."""
    inicio_instante = _interpretar_instante(inicio)
    fim_instante = _interpretar_instante(fim)
    if fim_instante <= inicio_instante:
        raise ErroDominio(ERRO_INTERVALO)

    validar_janela(inicio_instante, fim_instante)
    validar_duracao(inicio_instante, fim_instante)

    return inicio_instante, fim_instante


def validar_pedido(
    sala_id: str,
    inicio: str,
    fim: str,
    salas: Sequence[Sala],
) -> Sala:
    """Valida um pedido completo sem produzir efeitos."""
    sala = validar_sala(sala_id, salas)
    validar_intervalo(inicio, fim)
    return sala


def intervalos_se_sobrepoem(
    inicio_existente: str,
    fim_existente: str,
    inicio_novo: str,
    fim_novo: str,
) -> bool:
    """Compara intervalos por instantes, com bordas que nao se sobrepoem."""
    existente_inicio, existente_fim = (
        _interpretar_instante(inicio_existente),
        _interpretar_instante(fim_existente),
    )
    novo_inicio, novo_fim = (
        _interpretar_instante(inicio_novo),
        _interpretar_instante(fim_novo),
    )
    return existente_inicio < novo_fim and existente_fim > novo_inicio


def reservas_em_conflito(
    sala_id: str,
    inicio: str,
    fim: str,
    reservas: Sequence[Reserva],
) -> tuple[Reserva, ...]:
    """Retorna as reservas conflitantes da sala na ordem original."""
    return tuple(
        reserva
        for reserva in reservas
        if reserva.sala == sala_id
        and intervalos_se_sobrepoem(reserva.inicio, reserva.fim, inicio, fim)
    )


def alternativas_disponiveis(
    sala_pedida: Sala,
    inicio: str,
    fim: str,
    salas: Sequence[Sala],
    reservas: Sequence[Reserva],
    limite: int = 3,
) -> tuple[Sala, ...]:
    """Ordena ate tres salas livres com capacidade suficiente."""
    validar_intervalo(inicio, fim)
    candidatas = (
        sala
        for sala in salas
        if sala.id != sala_pedida.id
        and sala.capacidade >= sala_pedida.capacidade
        and not reservas_em_conflito(sala.id, inicio, fim, reservas)
    )
    return tuple(
        sorted(candidatas, key=lambda sala: (sala.capacidade, sala.id))[:limite]
    )


def _carregar_json(caminho: Path) -> Any:
    with caminho.open(encoding="utf-8") as arquivo:
        return json.load(arquivo)


def carregar_dominio(raiz: Path | None = None) -> Dominio:
    """Carrega os dados fornecidos sem depender do diretorio corrente."""
    raiz = raiz or Path(__file__).resolve().parents[1]
    dados = raiz / "dados"

    salas = tuple(
        Sala(
            id=item["id"],
            nome=item["nome"],
            capacidade=item["capacidade"],
            recursos=tuple(item["recursos"]),
        )
        for item in _carregar_json(dados / "salas.json")
    )
    reservas = tuple(
        Reserva(
            id=item["id"],
            sala=item["sala"],
            inicio=item["inicio"],
            fim=item["fim"],
            responsavel=item["responsavel"],
        )
        for item in _carregar_json(dados / "reservas.json")
    )
    texto_politica = (dados / "politica-de-uso.md").read_text(encoding="utf-8")
    primeira_linha = texto_politica.splitlines()[0]
    versao = primeira_linha.removeprefix("versao:").strip()

    return Dominio(
        salas=salas,
        reservas=reservas,
        politica=Politica(versao=versao, texto=texto_politica),
    )
