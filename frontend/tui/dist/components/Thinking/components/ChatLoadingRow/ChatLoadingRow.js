import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Box, Text } from '@ector/ink';
import { TranscriptCard } from '../../../TranscriptCard/index.js';
import { Spinner } from '../Spinner/index.js';
/** Indicador compacto no transcript enquanto o turno está ativo sem conteúdo ainda. */
export function ChatLoadingRow({
  label,
  t
}) {
  return _jsx(TranscriptCard, {
    t: t,
    tone: "userPlain",
    children: _jsxs(Box, {
      alignItems: "center",
      columnGap: 1,
      flexDirection: "row",
      children: [_jsx(Spinner, {
        color: t.color.cyan,
        variant: "think"
      }), _jsx(Text, {
        color: t.color.dim,
        dim: true,
        wrap: "wrap-trim",
        children: label
      })]
    })
  });
}