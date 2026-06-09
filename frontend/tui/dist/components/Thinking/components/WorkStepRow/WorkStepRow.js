import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Box, Text } from '@ector/ink';
import { compactPreview, edgePreview } from '../../../../lib/text.js';
import { Spinner } from '../Spinner/index.js';
const TITLE_MAX = 76;
const TECH_HEAD = 28;
const TECH_TAIL = 40;
/** Pure expand gate — exported for unit tests. */
export function workStepCanExpand(showTechnical, titleTrim, titlePreview, detailsLength) {
  return showTechnical || titleTrim.length > titlePreview.length || detailsLength > 0;
}
export function WorkStepRow({
  details = [],
  duration = '',
  expanded = false,
  marginBottom = 0,
  onToggle,
  status,
  technical = '',
  title,
  t
}) {
  const titleTrim = title.trim();
  const titlePreview = compactPreview(titleTrim, TITLE_MAX);
  const techTrim = technical.trim();
  const techCollapsed = edgePreview(techTrim, TECH_HEAD, TECH_TAIL);
  const showTechnical = Boolean(techTrim) && techTrim !== titleTrim && techTrim !== titlePreview && !titleTrim.startsWith(techTrim);
  const titleExpandable = titleTrim.length > titlePreview.length;
  const canExpand = workStepCanExpand(showTechnical, titleTrim, titlePreview, details.length);
  const titleDisplay = expanded && titleExpandable ? titleTrim : titlePreview || titleTrim || 'Ferramenta';
  const techDisplay = expanded ? techTrim : techCollapsed;
  const techWrap = 'wrap-trim';
  const statusNode = status === 'active' ? _jsx(Spinner, {
    color: t.color.cyan,
    variant: "tool"
  }) : status === 'error' ? _jsx(Text, {
    color: t.color.error,
    children: "\u2717"
  }) : _jsx(Text, {
    color: t.color.statusBarMeta,
    children: "\u2713"
  });
  const titleColor = status === 'error' ? t.color.error : t.color.text;
  return _jsxs(Box, {
    flexDirection: "column",
    marginBottom: marginBottom,
    onClick: canExpand ? onToggle : undefined,
    children: [_jsxs(Box, {
      columnGap: 1,
      flexDirection: "row",
      flexWrap: "wrap",
      children: [statusNode, _jsx(Text, {
        bold: status === 'active',
        color: titleColor,
        flexGrow: 1,
        wrap: "wrap-trim",
        children: titleDisplay
      }, "ws-title"), duration ? _jsx(Text, {
        color: t.color.statusBarMeta,
        dim: true,
        flexShrink: 0,
        children: duration
      }, "ws-dur") : null, canExpand ? _jsx(Text, {
        color: t.color.cyan,
        flexShrink: 0,
        children: expanded ? '▾' : '▸'
      }, "ws-hint") : null]
    }), showTechnical ? _jsx(Box, {
      paddingLeft: 2,
      children: _jsx(Text, {
        color: t.color.dim,
        dim: true,
        wrap: techWrap,
        children: techDisplay
      })
    }) : null, expanded && canExpand && details.length > 0 ? _jsx(Box, {
      flexDirection: "column",
      marginTop: 1,
      paddingLeft: 2,
      children: details.map(detail => _jsx(DetailBlock, {
        detail: detail
      }, detail.key))
    }) : null]
  });
}
function DetailBlock({
  detail
}) {
  if (detail.dimColor) {
    return _jsx(Text, {
      color: detail.color,
      dim: true,
      wrap: "wrap-trim",
      children: detail.content
    });
  }
  return _jsx(Text, {
    color: detail.color,
    wrap: "wrap-trim",
    children: detail.content
  });
}