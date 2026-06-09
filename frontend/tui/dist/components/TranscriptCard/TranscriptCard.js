import { jsx as _jsx } from "react/jsx-runtime";
import { Box } from '@ector/ink';
import { memo } from 'react';
export const TranscriptCard = memo(function TranscriptCard({
  children,
  marginBottom = 1,
  marginTop = 0,
  paddingX = 1,
  paddingY = 0,
  rounded = true,
  variant = 'neutral',
  t,
  tone = 'full'
}) {
  if (tone === 'userPlain') {
    return _jsx(Box, {
      flexDirection: "column",
      marginBottom: marginBottom,
      marginTop: marginTop,
      children: children
    });
  }
  // User bubbles: flat background + primary left border; assistant stays borderless.
  const bg = variant === 'assistant' ? t.color.bubbleAssistantBg : variant === 'user' ? t.color.bubbleUserBg : t.color.transcriptCardBg;
  const userAccentBorder = variant === 'user';
  return _jsx(Box, {
    backgroundColor: bg,
    borderLeft: userAccentBorder,
    borderLeftColor: userAccentBorder ? t.color.cyan : undefined,
    flexDirection: "column",
    flexGrow: 1,
    marginBottom: marginBottom,
    marginTop: marginTop,
    paddingX: paddingX,
    paddingY: paddingY,
    children: children
  });
});