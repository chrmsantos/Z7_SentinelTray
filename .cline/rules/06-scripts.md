---
paths:
  - "scripts/**"
  - "scripts/*.ps1"
  - "scripts/*.cmd"
---

# Regras de Scripts — Z7_SentinelTray

Regras ativadas ao editar scripts em `scripts/`.

## Scripts existentes

| Script | Propósito |
|---|---|
| `build_named_exe.cmd` | Wrapper CMD para o build PowerShell |
| `build_named_exe.ps1` | Build do executável via PyInstaller |
| `deploy.ps1` | Build + verificação do exe (chama `build_named_exe.ps1`) |
| `run.cmd` | Executa o app com venv e env `Z7_SENTINELTRAY_ROOT` |
| `activate_venv.cmd` | Abre terminal com venv ativado |
| `generate_icon.py` | Gera assets de ícone |

## Build (crítico)

- `build_named_exe.ps1`:
  - Usa PyInstaller com `--clean --noconfirm` (obrigatório para evitar truncamento).
  - Log em `config/logs/scripts/build_exe_<timestamp>.log`.
  - Mantém apenas os últimos 5 logs.
  - Procura Python em `.venv\Scripts\python.exe` → `runtime\python\python.exe` → `python`.
  - Verifica existência de `dist/Z7_SentinelTray.exe` ao final.
  - `$ErrorActionPreference = "Stop"` — falha rápido.

- `deploy.ps1`:
  - Chama `build_named_exe.ps1` primeiro.
  - Verifica tamanho do exe (em MB).
  - Não faz push/publicação (isso é feito manualmente ou via GitHub CLI).

## Ambiente

- `run.cmd` define `Z7_SENTINELTRAY_ROOT` e usa venv quando disponível.
- `activate_venv.cmd` usa `Activate.ps1` via PowerShell.

## Convenções PowerShell

- `$ErrorActionPreference = "Stop"`.
- Use `Join-Path` e `Resolve-Path` para caminhos (nunca concatenação de strings).
- Use `Test-Path` antes de acessar arquivos.
- Comentários explicativos para cada bloco.

## Ruff nos scripts

- Scripts ignoram `ANN` e `D` (não exigem type hints nem docstrings).
- Mantenha código limpo e legível mesmo sem verificações estritas.

## Ao modificar scripts de build

1. Teste localmente antes de propor mudanças.
2. Verifique que o `.spec` do PyInstaller é compatível.
3. Não remova `--clean --noconfirm` do PyInstaller.
4. Documente novos parâmetros e seu propósito.