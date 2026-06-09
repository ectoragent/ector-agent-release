import { coreCommands } from './commands/core.js';
import { debugCommands } from './commands/debug.js';
import { opsCommands } from './commands/ops.js';
import { rpcCommands } from './commands/rpc.js';
import { sessionCommands } from './commands/session.js';
import { setupCommands } from './commands/setup.js';
export const SLASH_COMMANDS = [...coreCommands, ...sessionCommands, ...rpcCommands, ...opsCommands, ...setupCommands, ...debugCommands];
const byName = new Map(SLASH_COMMANDS.flatMap(cmd => [cmd.name, ...(cmd.aliases ?? [])].map(name => [name, cmd])));
export const findSlashCommand = name => byName.get(name.toLowerCase());