# Configuração Cline — Z7_SentinelTray

Estrutura de configuração do Cline para este projeto, criada para otimizar
qualidade, performance, estabilidade, padronização e escalabilidade do
desenvolvimento no ambiente de chat.

## Estrutura

```
.cline/
├── custom_modes.json      # Modos personalizados (architect, coder, qa_tester, release_engineer)
├── rules/                 # Regras persistentes (sempre ativas + condicionais por caminho)
│   ├── 00-core-coding-standards.md
│   ├── 01-project-architecture.md
│   ├── 02-release-policy.md
│   ├── 03-source-python.md
│   ├── 04-tests-python.md
│   ├── 05-config-files.md
│   └── 06-scripts.md
├── skills/                # Skills sob demanda (carregadas apenas quando relevantes)
│   ├── build-and-deploy/
│   ├── run-tests/
│   └── version-bump/
└── hooks/                 # Hooks de ciclo de vida (build/test quality gates)
    ├── README.md
    └── project-hooks.js
```

## Sobre cada recurso

| Recurso | Local | Quando carrega | Uso neste projeto |
|---|---|---|---|
| **Rules** | `rules/*.md` | Sempre (ou condicional via `paths`) | Padrões de código, arquitetura, política de release |
| **Skills** | `skills/*/SKILL.md` | Sob demanda (auto-match ou slash command) | Build/deploy, testes, bump de versão |
| **Hooks** | `hooks/` | Em estágios do ciclo de vida | Quality gates, bloqueio de operações perigosas |
| **Modes** | `custom_modes.json` | Seleção manual | Architect, Coder, QA, Release Engineer |

## Ponto crítico: build e deploy

O procedimento de build e deploy no GitHub é **repetitivo, reincidente em erros
e frequentemente truncado**. Por isso foi padronizado em três camadas:

1. **Rule `02-release-policy.md`** — impõe a sequência obrigatória e os pontos
   de falha conhecidos (evita retrabalho).
2. **Skill `build-and-deploy/`** — passo a passo detalhado, carregado sob demanda.
3. **Hook de `afterRun`** — valida automaticamente o artefato `dist/Z7_SentinelTray.exe`
   após comandos de build.

## Manutenção

- Regras condicionais usam frontmatter `paths` (glob). Arquivos sem frontmatter são sempre ativos.
- Skills exigem `name` (idêntico ao nome do diretório) e `description` (máx. 1024 chars).
- Hooks seguem o formato do Cline SDK (JS/TS). Consulte `hooks/README.md`.
