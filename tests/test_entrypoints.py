from importlib import import_module

import pytest


@pytest.mark.parametrize(
    ("module_name", "expected_port"),
    [
        ("servidor_mcp.main", 7301),
        ("agente.main", 7300),
    ],
)
def test_process_entrypoints_load_with_default_environment(
    module_name: str, expected_port: int
) -> None:
    module = import_module(module_name)

    assert callable(module.main)
    assert module.DEFAULT_HOST == "127.0.0.1"
    assert module.DEFAULT_PORT == expected_port
