/** Selection styling is handled by the terminal cursor (declared cursor), not inverse-video. */
export function renderWithSelection(value, start, end) {
  if (start >= end) {
    return value;
  }
  return value;
}