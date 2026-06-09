import { jsx as _jsx } from "react/jsx-runtime";
import { useEffect, useMemo, useRef, useState } from 'react';
import { setInputSelection } from '../../app/inputSelectionStore.js';
import { writeClipboardText } from '../../lib/clipboard.js';
import { cursorLayout } from '../../lib/inputMetrics.js';
import { useFwdDelete } from './hooks/useFwdDelete.js';
import { useTextInputEditing } from './hooks/useTextInputEditing.js';
import { Box, stringWidth, Text, useDeclaredCursor, useStdout, useTerminalFocus } from './lib/inkRuntime.js';
import { renderWithSelection } from './lib/renderSelection.js';
import { offsetFromPosition } from './lineNav.js';
export function TextInput({
  columns = 80,
  value,
  onChange,
  onPaste,
  onSubmit,
  mask,
  placeholder = '',
  placeholderColor,
  focus = true,
  textColor
}) {
  const [cur, setCur] = useState(value.length);
  const [sel, setSel] = useState(null);
  const fwdDel = useFwdDelete(focus);
  const termFocus = useTerminalFocus();
  const {
    stdout
  } = useStdout();
  const curRef = useRef(cur);
  const selRef = useRef(null);
  const vRef = useRef(value);
  const self = useRef(false);
  const pasteBuf = useRef('');
  const pasteEnd = useRef(null);
  const pasteTimer = useRef(null);
  const pastePos = useRef(0);
  const editVersionRef = useRef(0);
  const parentChangeTimer = useRef(null);
  const pendingParentValue = useRef(null);
  const localRenderTimer = useRef(null);
  const lineWidthRef = useRef(stringWidth(value.includes('\n') ? value.slice(value.lastIndexOf('\n') + 1) : value));
  const undo = useRef([]);
  const redo = useRef([]);
  const cbChange = useRef(onChange);
  const cbSubmit = useRef(onSubmit);
  const cbPaste = useRef(onPaste);
  cbChange.current = onChange;
  cbSubmit.current = onSubmit;
  cbPaste.current = onPaste;
  const raw = self.current ? vRef.current : value;
  const display = mask ? raw.replace(/[^\n]/g, mask[0] ?? '*') : raw;
  const selected = useMemo(() => sel && sel.start !== sel.end ? {
    end: Math.max(sel.start, sel.end),
    start: Math.min(sel.start, sel.end)
  } : null, [sel]);
  const showingPlaceholder = focus && !display && !!placeholder;
  const layout = useMemo(() => cursorLayout(display, cur, columns), [columns, cur, display]);
  const textRef = useDeclaredCursor({
    line: layout.line,
    column: layout.column,
    active: focus && termFocus && !selected,
    style: 'line'
  });
  const rendered = useMemo(() => {
    if (!focus) {
      return display || (placeholder ? placeholder : ' ');
    }
    if (showingPlaceholder) {
      return placeholder;
    }
    if (selected) {
      return renderWithSelection(display, selected.start, selected.end);
    }
    return display || ' ';
  }, [display, focus, placeholder, selected, showingPlaceholder]);
  useEffect(() => {
    if (self.current) {
      self.current = false;
    } else {
      setCur(value.length);
      setSel(null);
      curRef.current = value.length;
      selRef.current = null;
      vRef.current = value;
      lineWidthRef.current = stringWidth(value.includes('\n') ? value.slice(value.lastIndexOf('\n') + 1) : value);
      undo.current = [];
      redo.current = [];
    }
  }, [value]);
  useEffect(() => {
    if (!focus || !selected) {
      return;
    }
    const text = vRef.current.slice(selected.start, selected.end);
    if (text) {
      void writeClipboardText(text);
    }
  }, [focus, selected]);
  useEffect(() => {
    if (!focus) {
      return;
    }
    setInputSelection({
      clear: () => {
        if (selRef.current) {
          selRef.current = null;
          setSel(null);
        }
      },
      end: selected?.end ?? curRef.current,
      start: selected?.start ?? curRef.current,
      value: vRef.current
    });
    return () => setInputSelection(null);
  }, [cur, focus, selected]);
  useEffect(() => () => {
    if (pasteTimer.current) {
      clearTimeout(pasteTimer.current);
    }
    if (parentChangeTimer.current) {
      clearTimeout(parentChangeTimer.current);
    }
    if (localRenderTimer.current) {
      clearTimeout(localRenderTimer.current);
    }
  }, []);
  const {
    clearSel,
    emitPaste
  } = useTextInputEditing({
    columns,
    focus,
    mask,
    refs: {
      cbChange,
      cbPaste,
      cbSubmit,
      curRef,
      editVersionRef,
      fwdDel,
      lineWidthRef,
      localRenderTimer,
      parentChangeTimer,
      pasteBuf,
      pasteEnd,
      pastePos,
      pasteTimer,
      pendingParentValue,
      redo,
      selRef,
      self,
      undo,
      vRef
    },
    setCur,
    setSel,
    stdout,
    termFocus
  });
  return _jsx(Box, {
    flexGrow: 1,
    flexShrink: 1,
    minWidth: 0,
    onClick: e => {
      if (!focus) {
        return;
      }
      clearSel();
      const next = offsetFromPosition(display, e.localRow ?? 0, e.localCol ?? 0, columns);
      setCur(next);
      curRef.current = next;
    },
    onMouseDown: e_0 => {
      if (!focus || e_0.button !== 2) {
        return;
      }
      emitPaste({
        cursor: curRef.current,
        hotkey: true,
        text: '',
        value: vRef.current
      });
    },
    width: "100%",
    children: _jsx(Text, {
      color: showingPlaceholder && placeholderColor ? placeholderColor : textColor,
      dimColor: !display && !!placeholder && !placeholderColor,
      ref: textRef,
      wrap: "wrap-char",
      children: rendered
    })
  });
}