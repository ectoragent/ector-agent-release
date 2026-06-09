import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Box } from '@ector/ink';
/** Lista de passos do painel Ferramentas — fundo discreto, sem árvore nem barra lateral. */
export function WorkStepsPanel({
  children,
  header,
  open,
  t
}) {
  return _jsxs(Box, {
    flexDirection: "column",
    marginBottom: 1,
    children: [header, open ? _jsx(Box, {
      backgroundColor: t.color.bubbleAssistantBg,
      flexDirection: "column",
      marginTop: 1,
      paddingX: 1,
      paddingY: 1,
      children: children
    }) : null]
  });
}