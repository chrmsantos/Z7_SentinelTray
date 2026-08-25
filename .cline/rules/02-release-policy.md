# Política de Release e Build/Deploy — Z7_SentinelTray

Regras **sempre ativas**. **CRÍTICO**: o build/deploy no GitHub é repetitivo e
tem sido truncado com erros reincidentes. Siga esta regra à risca.

## REGRA OBRIGATÓRIA (nunca pule)

Toda release estável **deve** ser publicada no GitHub com:

1. Tag git `v<X.Y.Z>` correspondente à versão.
2. Executável `dist/Z7_SentinelTray.exe` anexado como asset da release.

Isso é **estritamente obrigatório** para que o auto-update (`updater.py`) funcione
corretamente para todos os usuários finais.

## Sequência padrão de build/deploy

Use o skill `build-and-deploy` (slash command `/build-and-deploy`) para o
procedimento completo. Em resumo, a ordem é:

1. **Bump de versão** em `pyproject.toml` **e** `AI_CONTEXT.md` (sincronizados).
2. **Validar** com pytest + mypy + ruff (skill `run-tests`).
3. **Build** via `scripts\build_named_exe.cmd` → gera `dist\Z7_SentinelTray.exe`.
4. **Verificar** que o `.exe` existe e tem tamanho > 0.
5. **Commit** + **push** (branch atual).
6. **Criar tag** git `v<X.Y.Z>` e fazer push da tag.
7. **Criar GitHub release** com o `.exe` anexado como asset.

## Pontos de falha conhecidos (evite retrabalho)

- **PyInstaller trunca o build**: rode sempre com `--clean --noconfirm` (já configurado em `build_named_exe.ps1`).
- **Asset ausente na release**: confirme que `dist/Z7_SentinelTray.exe` existe antes de publicar.
- **Versão divergente**: `pyproject.toml`, `AI_CONTEXT.md`, tag e release devem usar a MESMA versão.
- **`hiddenimports`**: o spec deve conter `unicodedata` e `yaml` (já presentes).
- **Template de config no exe**: `datas=[('config/config.local.yaml.example', 'config')]` deve permanecer no spec.
- **Não rode o build** sem antes validar testes e sincronizar versão.

## Git

- Commits seguem Conventional Commits (ex.: `feat:`, `fix:`, `release:`, `docs:`, `style:`, `bump:`).
- Nunca faça `git push --force` para branch compartilhada.
- Tags: `v<MAJOR>.<MINOR>.<PATCH>` (ex.: `v6.7.2`).

## Para a IA (agente)

- **Nunca assuma que o build passou** — verifique a existência e o tamanho do `.exe`.
- **Nunca pule a validação de testes** antes de buildar.
- Se o build falhar, **leia o log** em `config\logs\scripts\build_exe_*.log` antes de tentar novamente.
- Se a publicação da release falhar, **verifique a tag e o asset** antes de repetir.
