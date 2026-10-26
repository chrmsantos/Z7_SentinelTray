---
name: version-bump
description: >
  Bump the project version consistently across all files (pyproject.toml,
  .cline/rules/01-project-architecture.md, .cline/rules/00-core-coding-standards.md,
  src/z7_sentineltray/__init__.py) following semantic versioning. Use when the user asks to
  bump version, update version, increment version, or prepare a new release version.
---

# Version Bump — Z7_SentinelTray

Atualização consistente de versão em todos os arquivos do projeto.

---

## Passo 1 — Verificar versão atual

```powershell
Select-String -Path pyproject.toml -Pattern 'version\s*='
Select-String -Path .cline/rules/01-project-architecture.md -Pattern 'Versão atual'
Select-String -Path .cline/rules/00-core-coding-standards.md -Pattern 'Versão atual'
Select-String -Path src/z7_sentineltray/__init__.py -Pattern '__version__|__version_label__|__release_date__'
```

> [!IMPORTANT]
> Os 4 arquivos devem estar sincronizados **antes e depois** do bump. O
> `src/z7_sentineltray/__init__.py` é a fonte da versão em runtime (GUI,
> `--version`, auto-update) — se ficar desatualizado, o `updater.py` compara a
> versão errada e oferece atualização em loop para a mesma release.

---

## Passo 2 — Definir nova versão

Siga **Semantic Versioning** (MAJOR.MINOR.PATCH):
- **MAJOR**: mudanças incompatíveis (raro para este projeto).
- **MINOR**: novas funcionalidades (ex.: novo botão, nova feature de monitoramento).
- **PATCH**: correções de bugs, ajustes internos.

Pergunte ao usuário qual número incrementar se não estiver claro.

---

## Passo 3 — Atualizar arquivos

São **4 arquivos** que devem ficar sincronizados:

### pyproject.toml

Altere a linha:
```toml
version = "X.Y.Z"
```

### .cline/rules/01-project-architecture.md

Altere a linha:
```markdown
- **Versão atual:** X.Y.Z
```

### .cline/rules/00-core-coding-standards.md

Altere a linha:
```markdown
- Versão atual: **X.Y.Z** (verifique `pyproject.toml` antes de alterar).
```

### src/z7_sentineltray/__init__.py

Altere as três constantes (a data usa formato `DD-MM-AAAA`):
```python
__version__ = "X.Y.Z"
__version_label__ = "X.Y.Z"
__release_date__ = "DD-MM-AAAA"
```

> [!WARNING]
> `__version__` alimenta o auto-update (`gui_app.py` → `run_update_check`) e
> `__version_label__` alimenta o título da GUI, o label de versão e `--version`.
> Esquecer este arquivo faz o `.exe` publicado se identificar com a versão
> anterior e o `updater.py` entrar em loop de "atualização" para a mesma release.

---

## Passo 4 — Verificar consistência

```powershell
$pyprojectVersion = (Select-String -Path pyproject.toml -Pattern 'version\s*=\s*"(.+)"').Matches.Groups[1].Value
$aiContextVersion = (Select-String -Path .cline/rules/01-project-architecture.md -Pattern '(?<=Versão atual:\*\* )[\d.]+').Matches.Value
$coreRulesVersion = (Select-String -Path .cline/rules/00-core-coding-standards.md -Pattern 'Versão atual: \*\*([\d.]+)\*\*').Matches[0].Groups[1].Value
$initVersion = (Select-String -Path src/z7_sentineltray/__init__.py -Pattern '__version__ = "([\d.]+)"').Matches[0].Groups[1].Value
if (($pyprojectVersion -eq $aiContextVersion) -and ($pyprojectVersion -eq $coreRulesVersion) -and ($pyprojectVersion -eq $initVersion)) {
    Write-Host "OK: Versão $pyprojectVersion consistente em todos os arquivos"
} else {
    Write-Error "ERRO: pyproject.toml=$pyprojectVersion, 01-project-architecture.md=$aiContextVersion, 00-core-coding-standards.md=$coreRulesVersion, __init__.py=$initVersion"
}
```

---

## Próximo passo

Após o bump de versão:
- Execute `run-tests` para validar.
- Execute `build-and-deploy` para buildar e publicar.