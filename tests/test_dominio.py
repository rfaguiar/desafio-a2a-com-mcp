from pathlib import Path

import pytest

from servidor_mcp.dominio import (
    ErroDominio,
    Reserva,
    Sala,
    alternativas_disponiveis,
    carregar_dominio,
    intervalos_se_sobrepoem,
    reservas_em_conflito,
    validar_pedido,
)


def test_carrega_dados_da_raiz_independentemente_do_diretorio_corrente(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    dominio = carregar_dominio()

    assert [sala.id for sala in dominio.salas] == [
        "sala-aquario",
        "sala-porao",
        "sala-garagem",
        "sala-fusca",
        "sala-mirante",
    ]
    assert [reserva.id for reserva in dominio.reservas] == [
        "res-0001",
        "res-0002",
    ]
    assert dominio.politica.versao == "2026-11-01"
    assert dominio.politica.texto.startswith("versao: 2026-11-01\n")


def test_valida_sala_e_intervalo_nos_limites_da_politica() -> None:
    dominio = carregar_dominio()

    sala = validar_pedido(
        "sala-aquario",
        "2026-11-03T08:00:00-03:00",
        "2026-11-03T10:00:00-03:00",
        dominio.salas,
    )

    assert sala.id == "sala-aquario"
    assert (
        validar_pedido(
            "sala-mirante",
            "2026-11-03T21:00:00+00:00",
            "2026-11-03T23:00:00+00:00",
            dominio.salas,
        ).id
        == "sala-mirante"
    )


@pytest.mark.parametrize(
    ("sala", "inicio", "fim", "mensagem"),
    [
        (
            "sala-delorean",
            "2026-11-03T09:00:00-03:00",
            "2026-11-03T10:00:00-03:00",
            "Sala inexistente: sala-delorean",
        ),
        (
            "sala-aquario",
            "2026-11-03T07:59:59-03:00",
            "2026-11-03T08:30:00-03:00",
            "Fora da janela de uso: a politica permite reservas entre 08:00 e 20:00",
        ),
        (
            "sala-aquario",
            "2026-11-03T19:30:00-03:00",
            "2026-11-03T20:00:01-03:00",
            "Fora da janela de uso: a politica permite reservas entre 08:00 e 20:00",
        ),
        (
            "sala-aquario",
            "2026-11-03T09:00:00-03:00",
            "2026-11-03T11:00:01-03:00",
            "Duracao acima do limite: a politica permite no maximo 2 horas",
        ),
        (
            "sala-aquario",
            "2026-11-03T10:00:00-03:00",
            "2026-11-03T09:00:00-03:00",
            "Intervalo invalido: fim deve ser posterior a inicio",
        ),
        (
            "sala-aquario",
            "2026-11-03T09:00:00-03:00",
            "2026-11-03T09:00:00-03:00",
            "Intervalo invalido: fim deve ser posterior a inicio",
        ),
    ],
)
def test_rejeita_pedidos_com_as_mensagens_literais(
    sala: str, inicio: str, fim: str, mensagem: str
) -> None:
    dominio = carregar_dominio()

    with pytest.raises(ErroDominio, match=f"^{mensagem}$"):
        validar_pedido(sala, inicio, fim, dominio.salas)


@pytest.mark.parametrize(
    ("inicio_consulta", "fim_consulta", "esperado"),
    [
        ("2026-11-03T13:00:00-03:00", "2026-11-03T14:00:00-03:00", False),
        ("2026-11-03T15:00:00-03:00", "2026-11-03T16:00:00-03:00", False),
        ("2026-11-03T14:00:00-03:00", "2026-11-03T14:01:00-03:00", True),
        ("2026-11-03T14:59:00-03:00", "2026-11-03T15:01:00-03:00", True),
    ],
)
def test_sobreposicao_permite_contato_apenas_nas_bordas(
    inicio_consulta: str, fim_consulta: str, esperado: bool
) -> None:
    assert (
        intervalos_se_sobrepoem(
            "2026-11-03T14:00:00-03:00",
            "2026-11-03T15:00:00-03:00",
            inicio_consulta,
            fim_consulta,
        )
        is esperado
    )


def test_lista_somente_reservas_em_conflito_da_sala() -> None:
    dominio = carregar_dominio()

    conflitos = reservas_em_conflito(
        "sala-garagem",
        "2026-11-03T14:30:00-03:00",
        "2026-11-03T15:30:00-03:00",
        dominio.reservas,
    )

    assert [reserva.id for reserva in conflitos] == ["res-0001"]


def test_ordena_alternativas_por_capacidade_e_id_limitando_a_tres() -> None:
    salas = (
        Sala("sala-pedida", "Pedida", 4, ()),
        Sala("sala-z", "Z", 6, ()),
        Sala("sala-b", "B", 8, ()),
        Sala("sala-a", "A", 8, ()),
        Sala("sala-extra", "Extra", 12, ()),
        Sala("sala-grande", "Grande", 20, ()),
    )
    reservas = (
        Reserva(
            "res-extra",
            "sala-z",
            "2026-11-03T09:00:00-03:00",
            "2026-11-03T10:00:00-03:00",
            "Doc",
        ),
    )

    alternativas = alternativas_disponiveis(
        salas[0],
        "2026-11-03T09:00:00-03:00",
        "2026-11-03T10:00:00-03:00",
        salas,
        reservas,
    )

    assert [sala.id for sala in alternativas] == ["sala-a", "sala-b", "sala-extra"]
