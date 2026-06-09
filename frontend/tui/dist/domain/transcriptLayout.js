/** Left gutter reserved for speaker label + anchor + gaps (virtual row height). */
export const SPEAKER_LINE_RESERVE_COLS = 16;
/** Indent tool / reasoning blocks under the transcript margin. */
export const TOOL_BLOCK_MARGIN_LEFT = 2;
/** Horizontal slack for round border + inner padding (virtual row width). */
export const TRANSCRIPT_CARD_HORIZONTAL_GUTTER = 2;
/** Extra vertical lines for round border + inner padding (virtual row height). */
export const TRANSCRIPT_CARD_VERTICAL_PAD = 1;
/** `transcript-inner` inset — keep in sync with `appLayout` + `branding`. */
export const TRANSCRIPT_INNER_PAD_LEFT = 2;
export const TRANSCRIPT_INNER_PAD_RIGHT = 2;
export const TRANSCRIPT_INNER_PAD_TOP = 1;
/** Scrollbar column beside `ScrollBox` (`marginLeft` + bar). */
export const TRANSCRIPT_SCROLLBAR_GUTTER = 2;
/** Usable transcript width (terminal cols minus chrome). */
export const transcriptContentCols = totalCols => Math.max(20, totalCols - TRANSCRIPT_INNER_PAD_LEFT - TRANSCRIPT_INNER_PAD_RIGHT - TRANSCRIPT_SCROLLBAR_GUTTER);
/** Inner padding of user/assistant chat bubbles (`TranscriptCard`). */
export const TRANSCRIPT_BUBBLE_PAD_X = 1;
export const TRANSCRIPT_BUBBLE_PAD_Y = 1;