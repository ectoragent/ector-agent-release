export const SETUP_REQUIRED_TITLE = 'Setup Required';
export const buildSetupRequiredSections = () => [{
  text: 'ECTOR needs a model provider before the TUI can start a session.'
}, {
  rows: [['/provider', 'configure provider + model in-place'], ['/setup', 'run full first-time setup wizard in-place'], ['Ctrl+C', 'exit and run `ECTOR setup` manually']],
  title: 'Actions'
}];