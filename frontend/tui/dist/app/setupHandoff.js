import { STATUS } from '../content/uiStatus.js';
import { patchUiState } from './uiStore.js';
export async function runExternalSetup({
  args,
  ctx,
  done,
  launcher,
  suspend
}) {
  const {
    gateway,
    session,
    transcript
  } = ctx;
  transcript.sys(`launching \`ECTOR ${args.join(' ')}\`…`);
  patchUiState({
    status: STATUS.setupRunning
  });
  let result = {
    code: null
  };
  await suspend(async () => {
    result = await launcher(args);
  });
  if (result.error) {
    transcript.sys(`error launching ECTOR: ${result.error}`);
    patchUiState({
      status: STATUS.setupRequired
    });
    return;
  }
  if (result.code !== 0) {
    transcript.sys(`ECTOR ${args[0]} exited with code ${result.code}`);
    patchUiState({
      status: STATUS.setupRequired
    });
    return;
  }
  const setup = await gateway.rpc('setup.status', {});
  if (setup?.provider_configured === false) {
    transcript.sys('still no provider configured');
    patchUiState({
      status: STATUS.setupRequired
    });
    return;
  }
  transcript.sys(done);
  session.newSession();
}