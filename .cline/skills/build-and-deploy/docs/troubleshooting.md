# Troubleshooting — Build & Deploy

## Erro: `PyInstaller` não encontrado

```cmd
.venv\Scripts\python.exe -m pip install pyinstaller
```

## Erro: build truncado / exe não funciona

- **Sempre** use `--clean --noconfirm` (já no script).
- Remova `build\pyinstaller` e `dist\` antes de rebuildar:
  ```cmd
  rmdir /s /q build\pyinstaller dist
  ```
- Verifique `hiddenimports` no `.spec`.

## Erro: `ModuleNotFoundError: No module named 'unicodedata'`

O spec já inclui `unicodedata`. Se o erro persistir, o PyInstaller pode não
estar detectando. Adicione explicitamente em `Z7_SentinelTray.spec`:
```python
hiddenimports=["unicodedata", "yaml"],
```

## Erro: tag já existe

```cmd
git tag -d vX.Y.Z
git push --delete origin vX.Y.Z
```
Depois recrie a tag com o passo 4.

## Erro: GitHub release falha

- Verifique que você está autenticado: `gh auth status`
- Verifique que o token tem permissão `repo`: `gh auth refresh -h github.com -s repo`
- O asset deve ser um arquivo existente e acessível.

## Erro: build passa mas exe não executa

- Rode o exe manualmente e capture o erro:
  ```cmd
  dist\Z7_SentinelTray.exe 2>&1 | Out-File -FilePath crash.log
  ```
- Verifique se `config/config.local.yaml.example` está incluído no bundle (campo `datas` no spec).