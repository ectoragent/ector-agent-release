import { jsx as _jsx } from "react/jsx-runtime";
import { Text } from '@ector/ink';
import { TreeRow } from '../TreeRow/index.js';
export function TreeTextRow({
  branch,
  color,
  content,
  dimColor,
  rails = [],
  t,
  wrap = 'wrap-trim'
}) {
  const text = dimColor ? _jsx(Text, {
    color: color,
    dim: true,
    wrap: wrap,
    children: content
  }) : _jsx(Text, {
    color: color,
    wrap: wrap,
    children: content
  });
  return _jsx(TreeRow, {
    branch: branch,
    rails: rails,
    t: t,
    children: [text]
  });
}