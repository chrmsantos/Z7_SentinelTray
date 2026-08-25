/**
 * Z7_SentinelTray — Project Hooks
 *
 * Quality gates e verificações de ciclo de vida para o agente Cline.
 * Segue o formato AgentPlugin do Cline SDK.
 *
 * Uso: registre este arquivo como plugin no ClineCore ou CLI.
 *   cline --plugin .cline/hooks/project-hooks.js "seu prompt"
 *
 * Compatibilidade: Cline SDK / CLI (não aplicável à extensão VS Code atualmente).
 *
 * @see https://docs.cline.bot/sdk/plugins
 */

/** @type {import("@cline/sdk").AgentPlugin} */
const projectHooks = {
  name: "z7-sentineltray-hooks",

  manifest: {
    capabilities: ["hooks"],
  },

  hooks: {
    /**
     * Bloqueia comandos destrutivos e operações perigosas.
     * failureMode: fail_closed = bloqueia se o hook falhar (segurança primeiro).
     */
    beforeTool(context) {
      const { toolName, toolInput } = context;

      // --- Bloqueio de comandos shell destrutivos ---
      if (toolName === "execute_command") {
        const command = (toolInput?.command || "").toLowerCase();

        const destructivePatterns = [
          /rm\s+-rf\s+\//,
          /rm\s+-rf\s+~(\/|$)/,
          /del\s+\/[sq]\s+\/[sq]\s+[a-z]:\\/i,
          /rd\s+\/[sq]\s+[a-z]:\\/i,
          /format\s+[a-z]:/i,
          /diskpart/i,
          />\s*\/dev\/sd[a-z]/,
        ];

        for (const pattern of destructivePatterns) {
          if (pattern.test(command)) {
            return {
              allowed: false,
              message:
                `🚫 BLOQUEADO: Comando destrutivo detectado: "${command}". ` +
                "Se isto for intencional, revise manualmente e execute fora do Cline.",
            };
          }
        }

        // Bloqueia git push --force para branches protegidas
        if (/git\s+push\s+.*--force/.test(command) && !/--force-with-lease/.test(command)) {
          return {
            allowed: false,
            message:
              "🚫 BLOQUEADO: git push --force detectado. Use --force-with-lease ou confirme manualmente.",
          };
        }

        // Bloqueia deleção de tags/branches remotas
        if (/git\s+push\s+.*--delete\s+origin/.test(command)) {
          return {
            allowed: false,
            message:
              "🚫 BLOQUEADO: Deleção remota de tag/branch detectada. Execute manualmente se necessário.",
          };
        }

        // Força --clean --noconfirm em builds PyInstaller
        if (
          /pyinstaller/i.test(command) &&
          !/--noconfirm/i.test(command)
        ) {
          return {
            allowed: false,
            message:
              '🚫 BLOQUEADO: PyInstaller sem --noconfirm. Adicione `--clean --noconfirm` ao comando.',
          };
        }
      }

      return { allowed: true };
    },

    /**
     * Verifica artefatos após comandos de build e teste.
     */
    afterTool(context) {
      const { toolName, toolInput, toolResult } = context;

      if (toolName === "execute_command") {
        const command = toolInput?.command || "";

        // Após build, verifica existência do exe
        if (
          /build_named_exe/i.test(command) ||
          /pyinstaller/i.test(command) ||
          /deploy\.ps1/i.test(command)
        ) {
          console.log("[Z7_HOOK] Build detectado — verifique dist/Z7_SentinelTray.exe");
          // Nota: a verificação real do arquivo requer acesso ao filesystem,
          // o que depende da API do SDK. Registre o alerta para o usuário.
          if (toolResult?.exitCode !== 0) {
            console.error(
              "[Z7_HOOK] ⚠️  Build falhou com exit code " +
                (toolResult?.exitCode ?? "?") +
                ". Verifique config/logs/scripts/build_exe_*.log"
            );
          }
        }

        // Após pytest, alerta sobre falhas
        if (/pytest/i.test(command)) {
          if (toolResult?.exitCode !== 0) {
            console.error(
              "[Z7_HOOK] ⚠️  Testes falharam. Corrija antes de fazer commit/build."
            );
          } else {
            console.log("[Z7_HOOK] ✅ Testes passaram.");
          }
        }
      }

      return { allowed: true };
    },

    /**
     * Timer e logging no início do run.
     */
    runStart(context) {
      context.metadata = context.metadata || {};
      context.metadata._startTime = Date.now();
      console.log(`[Z7_HOOK] Run iniciado às ${new Date().toISOString()}`);
      return { allowed: true };
    },

    /**
     * Métricas e duração no fim do run.
     */
    runEnd(context) {
      const start = context.metadata?._startTime;
      if (start) {
        const duration = ((Date.now() - start) / 1000).toFixed(1);
        console.log(`[Z7_HOOK] Run concluído em ${duration}s`);
      }
      return { allowed: true };
    },

    /**
     * Structured error reporting.
     */
    error(context) {
      console.error("[Z7_HOOK] Erro detectado:", {
        timestamp: new Date().toISOString(),
        message: context.error?.message ?? "Unknown error",
        category: "agent_error",
      });
      return { allowed: true };
    },
  },
};

// Export para Cline SDK / CLI
export default projectHooks;
module.exports = projectHooks;