# Hooks — Z7_SentinelTray

Hooks de ciclo de vida do agente Cline para quality gates e prevenção de erros.

## Formato

Os hooks seguem o formato do **Cline SDK** (`AgentPlugin` com objeto `hooks`).
Estágios disponíveis:

| Estágio | Quando dispara | Uso neste projeto |
|---|---|---|
| `before_agent_start` | Antes do agente iniciar | Injetar contexto do AI_CONTEXT.md |
| `run_start` | Início de cada run | Timer de build, logging |
| `tool_call_before` | Antes de executar ferramenta | Bloquear comandos destrutivos |
| `tool_call_after` | Após executar ferramenta | Verificar artefatos de build |
| `run_end` | Fim do run | Métricas, notificações |
| `error` | Em caso de erro | Structured error reporting |

## Políticas de hook

| Campo | Significado | Padrão |
|---|---|---|
| `mode` | `"blocking"` ou `"async"` | `"async"` |
| `timeoutMs` | Timeout do hook em ms | — |
| `retries` | Tentativas em caso de falha | 0 |
| `retryDelayMs` | Delay entre tentativas | — |
| `failureMode` | `"fail_open"` (continua) ou `"fail_closed"` (bloqueia) | `"fail_open"` |
| `maxConcurrency` | Execuções concorrentes máximas | — |
| `queueLimit` | Tamanho máximo da fila | — |

Use `failureMode: "fail_closed"` para hooks de enforcement (ex.: bloqueio de
comandos destrutivos). Use `"fail_open"` para hooks de observação (ex.: logging).

## Hooks implementados

Arquivo principal: `project-hooks.js`. Define:

1. **`tool_call_before`** (blocking, fail_closed):
   - Bloqueia `rm -rf`, `del /s /q`, `rd /s /q`, `format` e comandos similares.
   - Bloqueia `git push --force` para branches protegidas.
   - Bloqueia `git push --delete origin` (deleção de tags/branches remotas).
   - Bloqueia PyInstaller sem `--clean --noconfirm` (força flag de clean build).

2. **`tool_call_after`** (async, fail_open):
   - Após comandos de build (`build_named_exe.cmd`, `pyinstaller`, `deploy.ps1`),
     verifica que `dist/Z7_SentinelTray.exe` existe com tamanho > 0.
   - Após comandos de teste (`pytest`), captura o exit code e alerta sobre falhas.

3. **`error`** (async, fail_open):
   - Registra erros estruturados com timestamp, categoria e stack trace.

## Limitações

Hooks via plugins do Cline SDK aplicam-se ao **CLI e SDK**. A extensão VS Code
pode ter suporte limitado a hooks neste momento. Consulte a documentação
atualizada do Cline em https://docs.cline.bot/.

## Referências

- [Cline SDK Plugins Overview](https://docs.cline.bot/sdk/plugins)
- [Hook Stages](https://docs.cline.bot/sdk/plugins) — seção "Hook Stages"
- [Writing Plugins](https://docs.cline.bot/sdk/plugins/writing-plugins)