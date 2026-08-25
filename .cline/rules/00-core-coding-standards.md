# Core Coding Standards — Z7_SentinelTray

Regras **sempre ativas**. Aplicam-se a qualquer tarefa neste repositório.

## Linguagem e runtime

- Python **≥ 3.11**. Não use sintaxe de versões anteriores nem recursos que exijam 3.12+.
- Inicie módulos com `from __future__ import annotations` como primeira instrução.
- Encoding UTF-8 (sem BOM nos arquivos `.py`).

## Type hints (mypy strict)

- Type hints **obrigatórios** em todas as assinaturas de funções e métodos (públicos e privados).
- Proibido `Any` implícito. Use `collections.abc.Callable` e, quando inevitável, `dict[str, Any]` explícito.
- Anotações de retorno obrigatórias (`-> None`, `-> str`, etc.).
- Dataclasses de configuração e snapshot **devem** usar `frozen=True` (imutáveis).
- `strict = true` no mypy; não adicione `# type: ignore` sem justificativa.

## Logging estruturado

- Use sempre `extra={"category": "..."}` com uma destas categorias: `send`, `error`, `healthcheck`, `scan`, `perf`.
- Strings sensíveis (e-mails, caminhos) **devem** passar por `sanitize_text` antes de logar.
- Nunca logue senhas, tokens ou credenciais (SMTP via DPAPI).

## Escrita de arquivos

- Escrita de arquivos **sempre atômica** via `atomic_write_text` (nunca `write_text` direto em arquivos críticos).
- Caminhos resolvidos por `path_utils` (`ensure_under_root`, `resolve_log_path`, `resolve_sensitive_path`).
- Leitura de JSON via utilitários de `io_utils` (leitura segura).

## Lint e formatação (ruff)

- `line-length = 100`, aspas duplas, docstring estilo **Google**.
- `max-complexity = 12` (mccabe). Refatore funções que excedam.
- Ordem de imports (isort): `from __future__` → stdlib → third-party → first-party (`z7_sentineltray`).
- Selecione regras já habilitadas em `pyproject.toml` (E, W, F, I, D, UP, B, C90, ANN, PT, RUF, SIM, TRY, N).
- Não desligue regras do ruff sem justificativa explícita no PR/commit.

## Segurança

- Credenciais SMTP sempre via DPAPI (`dpapi_utils`), nunca em texto plano ou hardcoded.
- Caminhos sensíveis restritos ao diretório do usuário via `_apply_sensitive_path_policy`.
- Nunca faça commit de `config/config.local.yaml` (é ignorado pelo git).

## Versionamento

- Versão atual: **6.7.2** (verifique `pyproject.toml` antes de alterar).
- Toda mudança de versão deve ser consistente (ver skill `version-bump`).
