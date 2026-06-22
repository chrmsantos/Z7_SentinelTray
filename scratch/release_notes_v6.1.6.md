## Release v6.1.6 Stable

Esta versão traz novos recursos de robustez operacional e facilitação de atualizações para o **Z7_SentinelTray**, com foco em monitoramento contínuo em ambientes corporativos e detecção inteligente de estado do sistema.

### 🚀 Novidades e Melhorias
* **Sistema de Atualizações Automáticas:** Implementação de rotinas integradas para verificação de novas versões estáveis lançadas e atualização automatizada do executável de forma transparente para o usuário.
* **Detecção Inteligente de Tela Bloqueada (Windows Session Lock):** Aprimorado o tratamento de erro de janela indisponível (`WindowUnavailableError`). Agora o aplicativo detecta programaticamente se a sessão do usuário do Windows está bloqueada e anexa a observação `(a tela do usuário do windows está bloqueada)` nas mensagens de status e nos e-mails de alerta enviados. Isso evita falsos alertas e clarifica o diagnóstico operacional.
* **Estabilidade e Testes:** Refatoração e adição de testes robustos cobrindo a persistência do tema (claro/escuro) e cenários de indisponibilidade de janela sob bloqueio de tela, garantindo cobertura total de novos comportamentos.
