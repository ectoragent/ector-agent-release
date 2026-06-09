import { withInkSuspended } from '@ector/ink';
import { launchEctorCommand } from '../../../lib/externalCli.js';
import { runExternalSetup } from '../../setupHandoff.js';
export const setupCommands = [{
  help: 'assistente de configuração (executa `ECTOR setup`)',
  name: 'setup',
  run: (arg, ctx) => void runExternalSetup({
    args: ['setup', ...arg.split(/\s+/).filter(Boolean)],
    ctx,
    done: 'Configuração concluída — iniciando sessão…',
    launcher: launchEctorCommand,
    suspend: withInkSuspended
  })
}];