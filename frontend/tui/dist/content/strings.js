/** Mensagens user-facing em português (canónico). */
export const strings = {
  composer: {
    queued: preview => `na fila: "${preview}"`,
    shellExecFailed: 'falha ao executar comando shell'
  },
  gateway: {
    requestFailed: 'falha na requisição',
    invalidModelSwitch: 'resposta inválida: troca de modelo',
    invalidSessionResume: 'resposta inválida: session.resume',
    sessionError: message => `erro: ${message}`
  },
  rpc: {
    unknown: 'falha na requisição'
  },
  session: {
    nothingToCompress: 'nada para comprimir',
    nothingToUndo: 'nada para desfazer',
    nothingToRetry: 'nada para repetir',
    undidMessages: n => `desfez ${n} mensagem(ns)`,
    steerQueued: preview => `⏩ direcionamento na fila — chega após a próxima ferramenta: "${preview}"`,
    steerRejected: 'direcionamento rejeitado',
    steerNoTurn: preview => `sem turno ativo — na fila: "${preview}"`,
    saveFailed: 'falha ao salvar',
    savedTo: file => `conversa salva em: ${file}`,
    noConversation: 'ainda não há conversa',
    noActiveSession: 'nenhuma sessão ativa — nada para salvar'
  },
  slash: {
    ambiguous: list => `comando ambíguo: ${list}`,
    commandNoOutput: name => `/${name}: sem saída`,
    copyFailed: 'falha ao copiar — tente ECTOR_TUI_FORCE_OSC52=1; ECTOR_TUI_DEBUG_CLIPBOARD=1 para detalhes',
    copyUsage: 'uso: /copy [número]',
    copiedChars: n => `copiados ${n} caracteres`,
    nothingToCopy: 'nada para copiar',
    logsEmpty: 'sem logs do gateway',
    mouseUsage: 'uso: /mouse [on|off|toggle]',
    mouseTracking: on => `rastreamento do rato: ${on ? 'ligado' : 'desligado'}`,
    compactUsage: 'uso: /compact [on|off|toggle]',
    compact: on => `compacto: ${on ? 'ligado' : 'desligado'}`,
    details: (mode, overrides) => `detalhes: ${mode}${overrides ? `  (${overrides})` : ''}`,
    detailsSection: (section, mode) => `detalhes ${section}: ${mode}`,
    detailsUsage: 'uso: /details [hidden|collapsed|expanded|cycle]  ou  /details <secção> [hidden|collapsed|expanded|reset]',
    detailsSectionUsage: 'uso: /details <secção> [hidden|collapsed|expanded|reset]',
    fortuneUsage: 'uso: /fortune [random|daily]',
    pasteUsage: 'uso: /paste',
    queueCount: n => `${n} mensagem(ns) na fila`,
    queueEnqueued: preview => `na fila: "${preview}"`,
    statusBarUsage: 'uso: /statusbar [on|off|top|bottom|toggle]',
    statusBar: mode => `barra de status: ${mode}`,
    steerUsage: 'uso: /steer <prompt>',
    terminalSetupUsage: 'uso: /terminal-setup [auto|vscode|cursor|windsurf]',
    terminalSetupFailed: err => `configuração do terminal falhou: ${err}`,
    terminalRestartHint: 'reinicie o terminal da IDE para os atalhos novos terem efeito',
    backgroundUsage: '/background <prompt>',
    backgroundStarted: 'Segundo plano iniciado, você poder continuar a conversa anterior com /resume.',
    backgroundRunning: 'Segundo plano em execução…',
    backgroundRunningMany: n => `${n} tarefas em segundo plano…`,
    backgroundDismissed: 'Segundo plano dispensado na interface (a resposta ainda pode aparecer quando terminar).'
  }
};