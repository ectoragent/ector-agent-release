export const LOGIN_REQUIRED_TITLE = 'Login necessário';
export const buildLoginRequiredSections = () => [{
  text: 'A sessão ector.cc foi encerrada noutro terminal (por exemplo com `ector logout`). ' + 'O chat ficou pausado até voltar a autenticar-se.'
}, {
  rows: [['ector login', 'iniciar login no browser ou device code'], ['Ctrl+C', 'sair do TUI']],
  title: 'Próximos passos'
}];