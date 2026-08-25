---
paths:
  - "tests/**"
  - "tests/test_*.py"
---

# Padrões de Teste — Z7_SentinelTray

Regras ativadas ao escrever ou modificar testes em `tests/`.

## Framework e execução

- Framework: **pytest** com `pytest-cov`.
- Comando: `.venv\Scripts\python.exe -m pytest`
- Cobertura: branch coverage sobre `src/z7_sentineltray`.
- **Nunca faça commit com testes quebrados.**

## Isolamento

- `conftest.py` isola runtime via monkeypatch:
  - `Z7_SENTINELTRAY_DATA_DIR` → `tmp_path/config`
  - `Z7_SENTINELTRAY_ROOT` → `tmp_path/Root`
  - `LOCALAPPDATA` → isolado.
- Cada teste deve ser independente (sem estado compartilhado entre testes).
- Use `tmp_path` (pytest fixture) para diretórios temporários.

## Estrutura de nomeação

- Arquivos: `test_<modulo>.py` (ex.: `test_config.py`, `test_email_queue.py`).
- Funções: `test_<comportamento>()` descritivo.
- Fixtures em `conftest.py` ou no próprio arquivo de teste.

## Fixtures e dados estáticos

- Fixtures comuns: `conftest.py` (isolamento, monkeypatch de env).
- Dados estáticos: `tests/data/` (ex.: config.yaml de exemplo).
- Use parametrize para testar múltiplos cenários (`@pytest.mark.parametrize`).

## Arquivos de teste notáveis

| Arquivo | Cobre |
|---|---|
| `test_healthcheck_message.py` | Comportamento do healthcheck |
| `test_config_validation.py` | Validação de campos obrigatórios e limites |
| `test_detector*.py` | Leitura de janela, circuit breaker |
| `test_email_queue*.py` | Persistência e retry da fila |
| `test_error_reporting.py` | Cooldown e envio de notificações de erro |
| `test_build_named_exe_script.py` | Script de build |
| `test_debounce.py` | Deduplicação |
| `test_backoff.py` | Backoff config |
| `test_atomic_write.py` | Escrita atômica |

## Ruff nos testes

- Testes ignoram `ANN`, `D` e `SIM117` — não adicione type hints obrigatórios nem docstrings em testes.
- Comentários descritivos são bem-vindos para cenários complexos.

## Ao criar/alterar testes

1. Execute a suíte completa após a alteração.
2. Verifique cobertura com `--cov-report=term-missing`.
3. Não aceite regressões.