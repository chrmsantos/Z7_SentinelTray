---
paths:
  - "config/**"
  - "config/*.yaml"
  - "config/*.yml"
---

# Regras de Configuração — Z7_SentinelTray

Regras ativadas ao editar arquivos em `config/`.

## Template vs local

- `config/config.local.yaml` — **config real do usuário**, ignorada pelo git.
- `config/config.local.yaml.example` — **template documentado**, commitado.
- Nunca modifique `config.local.yaml.example` sem sincronizar com `config_reconcile.py`.

## Formato YAML

- Indentação: 2 espaços (consistente com o exemplo).
- Campos obrigatórios documentados em `config.local.yaml.example`.
- Sempre mantenha `config_version` atualizado.

## Sincronização de template

- `config_reconcile.py` faz merge de config existente com template.
- Ao adicionar um campo novo ao template, garanta que `_DEFAULT_CONFIG_VALUES` em `config.py` tenha um valor padrão correspondente.
- Testes de sincronização: `test_config_reconcile.py` e `test_config_template_sync.py`.

## Campos sensíveis

- Caminhos de log, fila e state são restritos ao diretório do usuário via `_apply_sensitive_path_policy`.
- Senhas SMTP nunca devem aparecer no template (apenas indicação de uso do DPAPI).
- `smtp_port` sempre entre 1 e 65535.

## Migração de versão

- `CURRENT_CONFIG_VERSION` em `config.py` (atualmente **1**).
- Migrações registradas em `_CONFIG_MIGRATIONS` — dicionário `{version: callable}`.
- Ao incrementar `CURRENT_CONFIG_VERSION`, registre a migração correspondente.

## Logs

- `config/logs/` contém logs operacionais e telemetria.
- `config/logs/scripts/` contém logs de build (`build_exe_*.log`, máximo 5 arquivos).
- Não commite arquivos de log.