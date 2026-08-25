---
name: version-bump
description: >
  Bump the project version consistently across all files (pyproject.toml,
  AI_CONTEXT.md) following semantic versioning. Use when the user asks to
  bump version, update version, increment version, or prepare a new release version.
---

# Version Bump — Z7_SentinelTray

Atualização consistente de versão em todos os arquivos do projeto.

---

## Passo 1 — Verificar versão atual

```powershell
Select-String -Path pyproject.toml -Pattern 'version\s*='
Select-String -Path AI_CONTEXT.md -Pattern 'Versão atual'
```

---

## Passo 2 — Definir nova versão

Siga **Semantic Versioning** (MAJOR.MINOR.PATCH):
- **MAJOR**: mudanças incompatíveis (raro para este projeto).
- **MINOR**: novas funcionalidades (ex.: novo botão, nova feature de monitoramento).
- **PATCH**: correções de bugs, ajustes internos.

Pergunte ao usuário qual número incrementar se não estiver claro.

---

## Passo 3 — Atualizar arquivos

### pyproject.toml

Altere a linha:
```toml
version = "X.Y.Z"
```

### AI_CONTEXT.md

Altere a linha:
```markdown
- **Versão atual:** X.Y.Z
```

---

## Passo 4 — Verificar consistência

```powershell
$pyprojectVersion = (Select-String -Path pyproject.toml -Pattern 'version\s*=\s*"(.+)"').Matches.Groups[1].Value
$aiContextVersion = (Select-String -Path AI_CONTEXT.md -Pattern '(?<=Versão atual:\*\* )[\d.]+').Matches.Value
if ($pyprojectVersion -eq $aiContextVersion) {
    Write-Host "OK: Versão $pyprojectVersion consistente"
} else {
    Write-Error "ERRO: pyproject.toml=$pyprojectVersion, AI_CONTEXT.md=$aiContextVersion"
}
```

---

## Próximo passo

Após o bump de versão:
- Execute `run-tests` para validar.
- Execute `build-and-deploy` para buildar e publicar.