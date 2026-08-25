---
name: build-and-deploy
description: >
  Build the named Windows executable (dist/Z7_SentinelTray.exe) via PyInstaller
  and publish a GitHub release with the exe attached as an asset. Use when the
  user asks to build, compile, deploy, release, publish, ship, or distribute a
  new version. Also use when the user mentions GitHub release, tag, or updater.
---

# Build & Deploy — Z7_SentinelTray

Procedimento completo para build do executável e publicação no GitHub.

**PRÉ-REQUISITOS**: A versão já deve estar definida (skill `version-bump`).
Os testes devem passar (skill `run-tests`). Se não estiverem prontos, execute
esses skills primeiro.

---

## Passo 1 — Verificar pré-requisitos

Antes de buildar, confirme:

```powershell
# Versão sincronizada entre pyproject.toml e AI_CONTEXT.md?
Select-String -Path pyproject.toml -Pattern 'version\s*=' | Select-Object -First 1
Select-String -Path AI_CONTEXT.md -Pattern 'Versão atual'
```

Se divergirem, execute o skill `version-bump` primeiro.

**Valide os testes**:

```cmd
.venv\Scripts\python.exe -m pytest
```

**NÃO PROSSIGA se houver falhas nos testes.**

---

## Passo 2 — Build do executável

```cmd
scripts\build_named_exe.cmd
```

Este script:
- Usa PyInstaller com `--clean --noconfirm` (previne truncamento).
- Gera log em `config\logs\scripts\build_exe_<timestamp>.log`.
- Verifica a existência do `.exe` ao final.

**Após o build, verifique:**

```powershell
$exe = "dist\Z7_SentinelTray.exe"
if (Test-Path $exe) {
    $info = Get-Item $exe
    Write-Host "OK: $($info.FullName) — $([math]::Round($info.Length / 1MB, 2)) MB"
} else {
    Write-Error "FALHA: $exe não encontrado!"
}
```

**Se falhar**, leia o log mais recente:

```powershell
Get-ChildItem config\logs\scripts\build_exe_*.log | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | Get-Content -Tail 50
```

Pontos de falha comuns:
- PyInstaller não instalado → `pip install pyinstaller`
- `hiddenimports` faltando → verifique `Z7_SentinelTray.spec` (já inclui `unicodedata`, `yaml`)
- Arquivos `.pyd`/`.dll` faltando → verifique se o venv está completo

---

## Passo 3 — Commit e push da versão

```cmd
git add pyproject.toml AI_CONTEXT.md
git commit -m "release: version X.Y.Z"
git push
```

---

## Passo 4 — Criar tag git

```cmd
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

**Confirme a tag:**

```cmd
git tag -l "vX.Y.Z"
```

---

## Passo 5 — Criar GitHub Release com asset

### Opção A — GitHub CLI (recomendado)

```cmd
gh release create vX.Y.Z dist\Z7_SentinelTray.exe --title "vX.Y.Z" --notes "Release notes aqui"
```

### Opção B — Interface web

1. Acesse: `https://github.com/chrmsantos/Z7_SentinelTray/releases/new?tag=vX.Y.Z`
2. Título: `vX.Y.Z`
3. Arraste `dist\Z7_SentinelTray.exe` para a área de assets.
4. Clique "Publish release".

---

## Passo 6 — Verificação final

1. Acesse a release page: `https://github.com/chrmsantos/Z7_SentinelTray/releases`
2. Confirme que a tag `vX.Y.Z` aparece.
3. Confirme que `Z7_SentinelTray.exe` está listado como asset.
4. Verifique que o arquivo tem o tamanho esperado (tipicamente ~12-15 MB).

**Isto é obrigatório** — sem o asset, o auto-update (`updater.py`) falha para
todos os usuários finais.

---

## Resumo do fluxo

```
version-bump → run-tests → build-exe → verificação → commit → tag → release → verificação-final
```

## Troubleshooting

Consulte [troubleshooting.md](docs/troubleshooting.md) para erros comuns.