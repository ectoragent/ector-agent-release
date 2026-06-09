import { spawn } from 'node:child_process';
const resolveEctorBin = () => process.env.ECTOR_BIN?.trim() || 'ector';
export const launchEctorCommand = args => new Promise(resolve => {
  const child = spawn(resolveEctorBin(), args, {
    stdio: 'inherit'
  });
  child.on('error', err => resolve({
    code: null,
    error: err.message
  }));
  child.on('exit', code => resolve({
    code
  }));
});