export const ESC = '\x1b';
export const FWD_DEL_RE = new RegExp(`${ESC}\\[3(?:[~$^]|;)`);
export const PRINTABLE = /^[ -~\u00a0-\uffff]+$/;
export const BRACKET_PASTE = new RegExp(`${ESC}?\\[20[01]~`, 'g');