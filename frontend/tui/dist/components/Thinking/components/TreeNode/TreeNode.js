import { jsx as _jsx } from "react/jsx-runtime";
import { Box } from '@ector/ink';
import { nextTreeRails } from '../../lib/treeLayout.js';
import { TreeRow } from '../TreeRow/index.js';
export function TreeNode({
  branch,
  children,
  header,
  open,
  rails = [],
  stemColor,
  stemDim,
  t
}) {
  return _jsx(Box, {
    flexDirection: "column",
    children: [rails.length > 0 ? _jsx(TreeRow, {
      branch: branch,
      rails: rails,
      stemColor: stemColor,
      stemDim: stemDim,
      t: t,
      children: header
    }, "tree-node-h") : _jsx(Box, {
      children: header
    }, "tree-node-h"), open ? children?.(nextTreeRails(rails, branch)) : null].filter(Boolean)
  });
}