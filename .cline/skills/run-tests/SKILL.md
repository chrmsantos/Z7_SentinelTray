---
name: run-tests
description: >
  Run the complete test suite for Z7_SentinelTray — pytest with branch coverage,
  mypy strict type checking, and ruff linting. Use when the user asks to test,
  validate, check, lint, type-check, or verify code quality before commits or releases.
---

# Run Tests — Z7_SentinelTray

Validação completa da qualidade do código.

---

## Passo 1 — pytest com cobertura

```cmd
.venv\Scripts\python.exe -m pytest
```

Flags automáticas (via `pyproject.toml`):
- `--cov=z7_sentineltray` — cobertura do pacote principal.
- `--cov-report=term-missing` — mostra linhas não cobertas.
- `--cov-report=html` — relatório HTML em `htmlcov/`.

**O que observar:**
- `FAILED` — teste quebrado. Corrija antes de prosseguir.
- Cobertura baixa — linhas não testadas listadas como `Missing`.
- Regressões — se um teste que passava antes agora falha.

---

## Passo 2 — mypy (type checking strict)

```cmd
.venv\Scripts\python.exe -m mypy src/z7_sentineltray
```

Configuração (`pyproject.toml`): `strict = true`, `disallow_any_generics = true`,
`disallow_untyped_defs = true`, `warn_return_any = true`.

**Não deve haver erros.** Se houver:
- `error: Function is missing a return type annotation` → adicione `-> ...`.
- `error: Returning Any from function` → tipifique explicitamente.
- `error: ... has type Any` → adicione anotação.

---

## Passo 3 — ruff (lint + format)

```cmd
.venv\Scripts\python.exe -m ruff check src/z7_sentineltray tests scripts
.venv\Scripts\python.exe -m ruff format --check src/z7_sentineltray tests scripts
```

**Regras aplicadas:** E, W, F, I, D, UP, B, C90, ANN, PT, RUF, SIM, TRY, N.

---

## Passo 4 — Resumo

| Etapa | Comando | Deve |
|---|---|---|
| Testes | `pytest` | Todos PASSED |
| Tipos | `mypy src/z7_sentineltray` | Sem erros |
| Lint | `ruff check` | Sem erros |
| Formato | `ruff format --check` | Sem diferenças |

Se todas as etapas passarem, o código está pronto para commit/build.

---

## Execução rápida (todas as etapas)

```cmd
.venv\Scripts\python.exe -m pytest && .venv\Scripts\python.exe -m mypy src/z7_sentineltray && .venv\Scripts\python.exe -m ruff check src/z7_sentineltray tests scripts && .venv\Scripts\python.exe -m ruff format --check src/z7_sentineltray tests scripts && echo "TUDO OK"
```