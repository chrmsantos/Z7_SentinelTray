# Arquitetura do Projeto — Z7_SentinelTray

Regras **sempre ativas**. Este documento é a fonte de verdade da arquitetura.

## Visão geral

**Z7_SentinelTray** é um notificador Windows que lê texto visível de uma janela
de aplicativo alvo e envia e-mail quando uma frase configurada aparece.
Roda como processo de console/`.exe` sem privilégios de administrador.

- **Versão atual:** 6.8.1
- **Python:** ≥ 3.11
- **Licença:** GPL-3.0-only
- **Autor:** CMS

---

## Estrutura do projeto

```
Z7_SentinelTray/
├── main.py                        # Ponto de entrada; adiciona src/ ao sys.path
├── cli.py                         # Alias de entrada CLI
├── pyproject.toml                 # Metadados, dependências dev, pytest, mypy, ruff
├── Z7_SentinelTray.spec           # Spec do PyInstaller
├── config/
│   ├── config.local.yaml          # Config real do usuário (ignorada pelo git)
│   ├── config.local.yaml.example  # Template com todos os campos documentados
│   └── logs/                      # Logs operacionais e telemetria
├── src/z7_sentineltray/           # Pacote principal
│   ├── entrypoint.py              # Guard single-instance, validação de startup, launch de UI
│   ├── app.py                     # Motor de monitoramento: Notifier, MonitorRuntime, loop principal
│   ├── config.py                  # Carregamento, validação e dataclasses de configuração
│   ├── config_reconcile.py        # Merge de config existente com template
│   ├── detector.py                # Leitura de texto de janela via Win32 API
│   ├── email_sender.py            # Envio SMTP, fila local, retry com backoff
│   ├── email_queue_utils.py       # Persistência e replay da fila de e-mail
│   ├── console_app.py             # Interface de console (menu interativo)
│   ├── gui_app.py                 # Interface gráfica (tray/janela)
│   ├── tray_app.py                # Ícone de bandeja do sistema
│   ├── updater.py                 # Mecanismo de atualização automática (auto-update)
│   ├── status.py                  # StatusStore thread-safe e StatusSnapshot imutável
│   ├── scan_utils.py              # Filtros de deduplicação, debounce, min_repeat
│   ├── idle_utils.py              # Detecção de ociosidade e bloqueio de tela
│   ├── dpapi_utils.py             # Criptografia de senha via Windows DPAPI
│   ├── logging_setup.py           # Setup de logging, sanitização, structured logs
│   ├── telemetry.py               # Escrita atômica de JSON de telemetria
│   ├── io_utils.py                # Utilitários de I/O (leitura segura de JSON, escrita atômica)
│   ├── path_utils.py              # Resolução de caminhos seguros
│   └── validation_utils.py        # Validação de e-mail e regex
├── tests/                         # Suite de testes pytest (55+ arquivos)
│   ├── conftest.py
│   ├── data/                      # Fixtures estáticas (config.yaml, etc.)
│   └── test_*.py
├── scripts/                       # Scripts auxiliares (build, deploy, venv)
├── docs/                          # Licenças de terceiros, notas de manutenção
├── assets/                        # Ícone e recursos visuais
└── tools/                         # Ferramentas externas empacotadas
```

## Mapa de módulos (`src/z7_sentineltray/`)
| Módulo | Responsabilidade |
|---|---|
| `entrypoint.py` | Guard single-instance (mutex + PID), validação de startup, launch de UI |
| `app.py` | Motor de monitoramento: `Notifier`, `MonitorRuntime`, loop principal |
| `config.py` | Carregamento, validação e dataclasses de configuração |
| `config_reconcile.py` | Merge de config existente com template |
| `detector.py` | Leitura de texto de janela via Win32 API (lança `WindowUnavailableError`) |
| `email_sender.py` | Envio SMTP, fila local, retry com backoff |
| `email_queue_utils.py` | Persistência e replay da fila de e-mail |
| `console_app.py` / `gui_app.py` / `tray_app.py` | Interfaces (console, gráfica, bandeja) |
| `updater.py` | Auto-update (botão da interface gráfica) |
| `status.py` | `StatusStore` thread-safe + `StatusSnapshot` imutável |
| `scan_utils.py` | Deduplicação, debounce, min_repeat |
| `idle_utils.py` | Detecção de ociosidade e bloqueio de tela |
| `dpapi_utils.py` | Criptografia de senha via Windows DPAPI |
| `logging_setup.py` | Setup de logging, sanitização, structured logs |
| `telemetry.py` | Escrita atômica de JSON de telemetria |
| `io_utils.py` | Utilitários de I/O |
| `path_utils.py` | Resolução de caminhos seguros |
| `validation_utils.py` | Validação de e-mail e regex |

---

## Módulos principais em detalhe

### `config.py`

- Dataclasses imutáveis (`frozen=True`): `AppConfig`, `MonitorConfig`, `EmailConfig`
- `load_config(path)` — lê YAML, aplica defaults, migra versões, valida
- `_DEFAULT_CONFIG_VALUES` — valores padrão para campos opcionais
- Campos sensíveis (caminhos de log, fila, state) são restritos ao diretório do usuário via `_apply_sensitive_path_policy`
- Variáveis de ambiente: `Z7_SENTINELTRAY_DATA_DIR`, `Z7_SENTINELTRAY_ROOT`

### `app.py`

- **`Notifier`** — classe central; gerencia o loop de scan, healthcheck, erros e envio
- **`MonitorRuntime`** — estado de runtime por monitor (histórico, circuit breaker/backoff desativados em runtime)
- Loop principal em `run()`: scan periódico, healthcheck, sem backoff exponencial em erros (funcionamento contínuo)
- `_send_healthcheck()` — envia status por e-mail; respeitando `healthcheck_send_on_error_only`
- `_handle_error()` — registra erro, envia notificação com cooldown
- `scan_once()` — executa uma iteração de varredura em todos os monitores
- Gatilho de segurança por atividade do usuário: trava a tela **antes** do envio do aviso (`idle_utils.lock_workstation`, controlada por `lock_screen_on_user_active_warning`), executada o mais rápido possível quando o gatilho dispara (primeira ação da iteração do loop, antes de check de disco, drain de filas e envio de e-mails); em seguida envia o aviso de segurança (`_send_user_active_warning`)

### `status.py`

- `StatusStore` — estado mutável thread-safe (Lock interno)
- `StatusSnapshot` — snapshot imutável retornado por `store.snapshot()`
- Campos relevantes: `last_error`, `error_count`, `last_healthcheck`, `last_send`, `last_scan`

### `detector.py`

- Lê texto visível da janela alvo via Win32 API
- Lança `WindowUnavailableError` se a janela não estiver acessível

### `email_sender.py`

- `EmailSender` — interface base
- `QueueingEmailSender` — persiste e-mails em fila JSON se o SMTP falhar; retry com backoff
- `build_sender(config)` — fábrica que retorna o sender adequado

---

## Fluxo de execução

```
main.py → entrypoint.py
  └─ guard single-instance (mutex + PID file)
  └─ load_config()
  └─ console_app ou gui_app
       └─ Notifier.run()
            ├─ scan loop (poll_interval_seconds)
            │    └─ detector → scan_utils → email_sender
            ├─ healthcheck (healthcheck_interval_seconds)
            └─ sem backoff em erros (contínuo)
```

## Dados em runtime (fora do repositório)

| Artefato | Localização |
|---|---|
| Config do usuário | `%LOCALAPPDATA%\ZWave\Tmp\Z7_SentinelTray\Config\config.local.yaml` |
| Logs | `%LOCALAPPDATA%\ZWave\Tmp\Z7_SentinelTray\Config\logs\` |
| State (deduplicação) | `%LOCALAPPDATA%\ZWave\Tmp\Z7_SentinelTray\Config\state.json` |
| Senha SMTP (DPAPI) | `%LOCALAPPDATA%\ZWave\Tmp\Z7_SentinelTray\Config\smtp_password_<n>.dpapi` |
| PID file | `%LOCALAPPDATA%\ZWave\Tmp\Z7_SentinelTray\Config\z7_sentineltray.pid` |

Sobrescrito por `Z7_SENTINELTRAY_DATA_DIR` (usada em testes via `conftest.py`).

## Variáveis de ambiente

- `Z7_SENTINELTRAY_DATA_DIR` — sobrescreve o diretório de dados.
- `Z7_SENTINELTRAY_ROOT` — sobrescreve a raiz do projeto.

---

## Configuração

Todos os campos estão documentados em [`config/config.local.yaml.example`](../../config/config.local.yaml.example).

Campos-chave:

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `poll_interval_seconds` | int | — | Intervalo entre scans |
| `healthcheck_interval_seconds` | int | — | Intervalo entre healthchecks |
| `healthcheck_send_on_error_only` | bool | `true` | Envia e-mail de healthcheck só se houver erro ativo |
| `log_only_mode` | bool | — | Não envia alertas normais; erros ainda são enviados |
| `debounce_seconds` | int | — | Janela de supressão de alertas repetidos por monitor |
| `send_repeated_matches` | bool | `true` | Permite reenvio de match idêntico após `min_repeat_seconds` |
| `error_notification_cooldown_seconds` | int | `300` | Rate-limit de notificações de erro |
| `pause_on_user_active` | bool | `true` | Pausa scans enquanto usuário está ativo |
| `pause_idle_threshold_seconds` | int | `180` | Segundos de ociosidade antes de retomar scans |
| `lock_screen_on_user_active_warning` | bool | `true` | Bloqueia a tela (Win+L) junto com o aviso de segurança |

Padrões definidos em `_DEFAULT_CONFIG_VALUES` (`config.py`):
`error_notification_cooldown_seconds=300`, `pause_on_user_active=True`,
`pause_idle_threshold_seconds=180`, `healthcheck_send_on_error_only=True`,
`lock_screen_on_user_active_warning=True`,
`send_repeated_matches=True`.

---

## Build e distribuição

```cmd
# Build do executável nomeado (sem admin)
scripts\build_named_exe.cmd

# Resultado
dist\Z7_SentinelTray.exe
```

O spec do PyInstaller está em `Z7_SentinelTray.spec`. O `.exe` inclui o template de config e assets.

> [!IMPORTANT]
> **Políticas de Lançamento e Atualização:**
> - Releases estáveis devem **sempre ser publicadas no GitHub** com a tag Git (ex: `v6.1.7`) e o `.exe` anexado como asset.
> - Esse procedimento é obrigatório para o `updater.py` funcionar.
> - Veja a regra `02-release-policy.md` para o procedimento completo.
