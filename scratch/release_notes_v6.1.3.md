## Release v6.1.3 Stable

Esta versão traz uma correção crucial de usabilidade e alinhamento visual no **Z7_SentinelTray**, garantindo que os botões do rodapé e a barra inferior permaneçam perfeitamente visíveis sob qualquer resolução ou redimensionamento de janela.

### 🚀 Correções e Melhorias
* **Fix de Visibilidade do Rodapé:** Ajustada a ordem de empacotamento (`pack`) do Tkinter na construção da tela inicial. O rodapé agora é fixado na parte inferior (`side=tk.BOTTOM`) **antes** que a área central com duas colunas seja alocada.
* **Redimensionamento Automático Inteligente:** Com esta alteração, quando a janela é redimensionada ou exibida em telas com menores resoluções, os quadros do corpo central (incluindo o novo quadro de *Janelas Ativas* e o de *Monitores*) encolhem proporcionalmente de forma automática e ativam suas barras de rolagem integradas, mantendo os botões inferiores e informações de licença 100% visíveis e acessíveis em tempo integral.
* Contém todas as novidades de performance extrema e monitoramento nativo por Ctypes introduzidos na `v6.1.2`.
