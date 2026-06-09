/**
 * Map Ink-style layout props to OpenTUI box/text style objects.
 * Used by the incremental Ink → OpenTUI compat layer.
 */
export const inkBoxStyle = props => {
  const style = {};
  if (props.backgroundColor) {
    style.backgroundColor = props.backgroundColor;
  }
  if (props.borderColor) {
    style.borderColor = props.borderColor;
  }
  if (props.flexDirection) {
    style.flexDirection = props.flexDirection;
  }
  if (props.flexGrow != null) {
    style.flexGrow = props.flexGrow;
  }
  if (props.flexShrink != null) {
    style.flexShrink = props.flexShrink;
  }
  if (props.height != null) {
    style.height = props.height;
  }
  if (props.width != null) {
    style.width = props.width;
  }
  if (props.minWidth != null) {
    style.minWidth = props.minWidth;
  }
  const padX = props.paddingX ?? props.padding;
  const padY = props.paddingY ?? props.padding;
  if (padX != null) {
    style.paddingLeft = padX;
    style.paddingRight = padX;
  }
  if (padY != null) {
    style.paddingTop = padY;
    style.paddingBottom = padY;
  }
  if (props.paddingLeft != null) {
    style.paddingLeft = props.paddingLeft;
  }
  if (props.paddingRight != null) {
    style.paddingRight = props.paddingRight;
  }
  if (props.paddingTop != null) {
    style.paddingTop = props.paddingTop;
  }
  if (props.paddingBottom != null) {
    style.paddingBottom = props.paddingBottom;
  }
  if (props.marginTop != null) {
    style.marginTop = props.marginTop;
  }
  if (props.marginBottom != null) {
    style.marginBottom = props.marginBottom;
  }
  if (props.marginLeft != null) {
    style.marginLeft = props.marginLeft;
  }
  if (props.marginRight != null) {
    style.marginRight = props.marginRight;
  }
  return style;
};