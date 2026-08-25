---
paths:
  - "src/**"
  - "src/z7_sentineltray/**"
---

# Convenções de Código Fonte — Z7_SentinelTray

Regras ativadas quando se trabalha com código em `src/z7_sentineltray/`.

## Estrutura de módulos

- Cada módulo trata de uma responsabilidade única (ver `01-project-architecture.md`).
- Novos módulos devem ser registrados em `AI_CONTEXT.md` com descrição.
- Nenhum módulo deve exceder ~500 linhas sem justificativa.

## Dataclasses

- Objetos de configuração e snapshot: **`frozen=True` obrigatório**.
- Use `field(default=...)` para valores padrão; nunca use parâmetros mutáveis.
- `replace()` para criar cópia com alterações (já que frozen).

## Padrões de erro

- Exceções customizadas herdam de `Exception`, com mensagem descritiva.
- `detector.py` lança `WindowUnavailableError` — capture-a adequadamente em `app.py`.
- `config.py` levanta `ValueError` para validação de campos.

## Thread safety

- `StatusStore` usa `Lock` interno — snapshot via `store.snapshot()`.
- `QueueingEmailSender` protege acesso à fila com lock.
- Não adicione estado compartilhado sem proteção de thread.

## Logging e telemetria

- Categorias de log: `send`, `error`, `healthcheck`, `scan`, `perf`.
- Use `LOGGER = logging.getLogger(__name__)` no topo do módulo.
- Telemetria via `telemetry.py` (escrita atômica de JSON).
- MonitorRuntime controla estado de runtime por monitor (histórico, circuit breaker).

## Email Sender

- Interface base: `EmailSender`.
- Implementação principal: `QueueingEmailSender` (persiste + retry com backoff).
- Fábrica: `build_sender(config)` retorna o sender adequado.
- Nunca envie e-mail bloqueando a thread principal por longos períodos.

## Config

- `_DEFAULT_CONFIG_VALUES` define padrões — não os duplique em outro lugar.
- Migrações de versão em `_CONFIG_MIGRATIONS`.
- `_apply_sensitive_path_policy` restringe caminhos ao diretório do usuário.