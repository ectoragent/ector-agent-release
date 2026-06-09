export const ROLE = {
  assistant: t => ({
    body: t.color.text,
    boldBody: false,
    chip: 'Assistente',
    chipColor: t.color.label,
    anchor: '▎',
    anchorColor: t.color.border,
    prefix: t.color.border
  }),
  system: t => ({
    body: '',
    boldBody: false,
    chip: '',
    chipColor: t.color.dim,
    anchor: '·',
    anchorColor: t.color.dim,
    prefix: t.color.dim
  }),
  tool: t => ({
    body: t.color.dim,
    boldBody: false,
    chip: '',
    chipColor: t.color.dim,
    anchor: '⚡',
    anchorColor: t.color.dim,
    prefix: t.color.dim
  }),
  user: t => ({
    body: t.color.label,
    boldBody: false,
    chip: 'Você',
    chipColor: t.color.label,
    anchor: t.brand.prompt,
    anchorColor: t.color.cyan,
    prefix: t.color.label
  })
};