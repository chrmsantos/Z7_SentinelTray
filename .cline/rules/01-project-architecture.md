# Arquitetura do Projeto — Z7_SentinelTray

Regras **sempre ativas**. Fonte de verdade: `AI_CONTEXT.md` (raiz do repositório).

## Visão geral

**Z7_SentinelTray** é um notificador Windows que lê texto visível de uma janela
de aplicativo alvo e envia e-mail quando uma frase configurada aparece.
Roda como processo de console/`.exe` sem privilégios de administrador.

- Licença: GPL-3.0-only · Autor: CMS

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
| `idle_utils.py` | Detecção de ociosidade do usuário |
| `dpapi_utils.py` | Criptografia de senha via Windows DPAPI |
| `logging_setup.py` | Setup de logging, sanitização, structured logs |
| `telemetry.py` | Escrita atômica de JSON de telemetria |
| `io_utils.py` | Utilitários de I/O |
| `path_utils.py` | Resolução de caminhos seguros |
| `validation_utils.py` | Validação de e-mail e regex |

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

## Constantes de configuração relevantes

Consulte `config/config.local.yaml.example` para todos os campos. Padrões em
`_DEFAULT_CONFIG_VALUES` (`config.py`): `error_notification_cooldown_seconds=300`,
`pause_on_user_active=True`, `pause_idle_threshold_seconds=180`,
`healthcheck_send_on_error_only=True`, `send_repeated_matches=True`.
