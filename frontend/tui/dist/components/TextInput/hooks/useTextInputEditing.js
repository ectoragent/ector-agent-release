import { isMouseInputLeak, stripMouseLeakFragments } from '@ector/ink';
import { readClipboardText, writeClipboardText } from '../../../lib/clipboard.js';
import { isActionMod, isMac, isMacActionFallback } from '../../../lib/platform.js';
import { stringWidth, supportsTerminalFastEcho, useInput } from '../lib/inkRuntime.js';
import { BRACKET_PASTE, PRINTABLE } from '../lib/keyPatterns.js';
import { isPasteResultPromise } from '../lib/pasteTypes.js';
import { lineNav, nextGraphemePos as nextPos, prevGraphemePos as prevPos, snapGraphemePos as snapPos, wordLeft, wordRight } from '../lineNav.js';
export function useTextInputEditing(opts) {
  const {
    columns,
    focus,
    mask,
    refs,
    setCur,
    setSel,
    stdout,
    termFocus
  } = opts;
  const {
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
  } = refs;
  const flushParentChange = () => {
    if (parentChangeTimer.current) {
      clearTimeout(parentChangeTimer.current);
      parentChangeTimer.current = null;
    }
    const next = pendingParentValue.current;
    pendingParentValue.current = null;
    if (next !== null) {
      self.current = true;
      cbChange.current(next);
    }
  };
  const scheduleParentChange = next_0 => {
    pendingParentValue.current = next_0;
    if (parentChangeTimer.current) {
      return;
    }
    parentChangeTimer.current = setTimeout(flushParentChange, 16);
  };
  const cancelLocalRender = () => {
    if (localRenderTimer.current) {
      clearTimeout(localRenderTimer.current);
      localRenderTimer.current = null;
    }
  };
  const scheduleLocalRender = () => {
    if (localRenderTimer.current) {
      return;
    }
    localRenderTimer.current = setTimeout(() => {
      localRenderTimer.current = null;
      setCur(curRef.current);
    }, 16);
  };
  const canFastEchoBase = () => supportsTerminalFastEcho() && focus && termFocus && !(selRef.current && selRef.current.start !== selRef.current.end) && !mask && !!stdout?.isTTY;
  const canFastAppend = (current, cursor, text) => {
    // Espaço/tab e outros whitespace: nunca ecoar direto no TTY — com cursor em
    // bloco (useDeclaredCursor) o fast-echo deixa células invertidas/pretas entre palavras.
    if (text.length === 1 && /\s/.test(text)) {
      return false;
    }
    const sw = stringWidth(text);
    return canFastEchoBase() && cursor === current.length && current.length > 0 && !current.includes('\n') && sw === text.length && lineWidthRef.current + sw < Math.max(1, columns);
  };
  const canFastBackspace = (current_0, cursor_0) => {
    if (!canFastEchoBase() || cursor_0 !== current_0.length || cursor_0 <= 0 || current_0.includes('\n')) {
      return false;
    }
    return stringWidth(current_0.slice(prevPos(current_0, cursor_0), cursor_0)) === 1;
  };
  const commit = (next_1, nextCur, track = true, syncParent = true, syncLocal = true, nextLineWidth) => {
    const prev = vRef.current;
    const c = snapPos(next_1, nextCur);
    editVersionRef.current += 1;
    if (selRef.current) {
      selRef.current = null;
      setSel(null);
    }
    if (track && next_1 !== prev) {
      undo.current.push({
        cursor: curRef.current,
        value: prev
      });
      if (undo.current.length > 200) {
        undo.current.shift();
      }
      redo.current = [];
    }
    if (syncLocal) {
      cancelLocalRender();
      setCur(c);
    } else {
      scheduleLocalRender();
    }
    curRef.current = c;
    vRef.current = next_1;
    lineWidthRef.current = nextLineWidth ?? stringWidth(next_1.includes('\n') ? next_1.slice(next_1.lastIndexOf('\n') + 1) : next_1);
    if (next_1 !== prev) {
      if (syncParent) {
        flushParentChange();
        self.current = true;
        cbChange.current(next_1);
      } else {
        self.current = true;
        scheduleParentChange(next_1);
      }
    }
  };
  const swap = (from, to) => {
    const entry = from.current.pop();
    if (!entry) {
      return;
    }
    to.current.push({
      cursor: curRef.current,
      value: vRef.current
    });
    commit(entry.value, entry.cursor, false);
  };
  const emitPaste = e => {
    const startVersion = editVersionRef.current;
    const h = cbPaste.current?.(e);
    if (isPasteResultPromise(h)) {
      const fallbackText = e.text;
      void h.then(result => {
        if (result && editVersionRef.current === startVersion) {
          commit(result.value, result.cursor);
        } else if (result && fallbackText && PRINTABLE.test(fallbackText)) {
          // User typed while async paste was in-flight — fall back to raw text insert
          // so the pasted content is not silently lost.
          const cur = curRef.current;
          const v = vRef.current;
          commit(v.slice(0, cur) + fallbackText + v.slice(cur), cur + fallbackText.length);
        }
      }).catch(() => {});
      return true;
    }
    if (h) {
      commit(h.value, h.cursor);
    }
    return !!h;
  };
  const flushPaste = () => {
    const text_0 = pasteBuf.current;
    const at = pastePos.current;
    const end = pasteEnd.current ?? at;
    pasteBuf.current = '';
    pasteEnd.current = null;
    pasteTimer.current = null;
    if (!text_0) {
      return;
    }
    if (!emitPaste({
      cursor: at,
      text: text_0,
      value: vRef.current
    }) && PRINTABLE.test(text_0)) {
      commit(vRef.current.slice(0, at) + text_0 + vRef.current.slice(end), at + text_0.length);
    }
  };
  const clearSel = () => {
    if (!selRef.current) {
      return;
    }
    selRef.current = null;
    setSel(null);
  };
  const selectAll = () => {
    const end_0 = vRef.current.length;
    if (!end_0) {
      return;
    }
    const next_2 = {
      end: end_0,
      start: 0
    };
    selRef.current = next_2;
    setSel(next_2);
    setCur(end_0);
    curRef.current = end_0;
  };
  const selRange = () => {
    const range = selRef.current;
    return range && range.start !== range.end ? {
      end: Math.max(range.start, range.end),
      start: Math.min(range.start, range.end)
    } : null;
  };
  const ins = (v_0, c_0, s) => v_0.slice(0, c_0) + s + v_0.slice(c_0);
  const pastePlainText = text_1 => {
    const cleaned = text_1.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    if (!cleaned) {
      return;
    }
    const range_0 = selRange();
    const nextValue = range_0 ? vRef.current.slice(0, range_0.start) + cleaned + vRef.current.slice(range_0.end) : vRef.current.slice(0, curRef.current) + cleaned + vRef.current.slice(curRef.current);
    const nextCursor = range_0 ? range_0.start + cleaned.length : curRef.current + cleaned.length;
    commit(nextValue, nextCursor);
  };
  useInput((rawInp, k, event) => {
    const eventRaw = event.keypress.raw ?? '';
    if (isMouseInputLeak(eventRaw, rawInp)) {
      return;
    }
    const inp = stripMouseLeakFragments(rawInp);
    if (rawInp && !inp) {
      return;
    }
    if (eventRaw === '\x1bv' || eventRaw === '\x1bV' || eventRaw === '\x16' || isMac && isActionMod(k) && inp.toLowerCase() === 'v') {
      if (cbPaste.current) {
        return void emitPaste({
          cursor: curRef.current,
          hotkey: true,
          text: '',
          value: vRef.current
        });
      }
      if (isMac) {
        void readClipboardText().then(text_2 => {
          if (text_2) {
            pastePlainText(text_2);
          }
        });
      }
      return;
    }
    if (isMac && isActionMod(k) && inp.toLowerCase() === 'c') {
      const range_1 = selRange();
      if (range_1) {
        const text_3 = vRef.current.slice(range_1.start, range_1.end);
        void writeClipboardText(text_3);
      }
      return;
    }
    if (k.upArrow || k.downArrow) {
      const next_3 = lineNav(vRef.current, curRef.current, k.upArrow ? -1 : 1);
      if (next_3 !== null) {
        clearSel();
        setCur(next_3);
        curRef.current = next_3;
        return;
      }
      return;
    }
    // Ctrl+B is the documented voice-recording toggle (see platform.ts →
    // isVoiceToggleKey). Pass it through so the app-level handler in
    // useInputHandlers receives it instead of being swallowed here as
    // either backward-word nav (line below) or a literal 'b' insertion.
    if (k.ctrl && inp === 'c' || k.ctrl && inp === 'b' || k.tab || k.shift && k.tab || k.pageUp || k.pageDown || k.escape) {
      return;
    }
    if (k.return) {
      if (k.shift || k.ctrl || (isMac ? isActionMod(k) : k.meta)) {
        flushParentChange();
        commit(ins(vRef.current, curRef.current, '\n'), curRef.current + 1);
      } else {
        flushParentChange();
        cbSubmit.current?.(vRef.current);
      }
      return;
    }
    let c_1 = curRef.current;
    let v_1 = vRef.current;
    const mod = isActionMod(k);
    const wordMod = mod || k.meta;
    const actionHome = k.home || !isMac && mod && inp === 'a' || isMacActionFallback(k, inp, 'a');
    const actionEnd = k.end || mod && inp === 'e' || isMacActionFallback(k, inp, 'e');
    const actionDeleteToStart = mod && inp === 'u' || isMacActionFallback(k, inp, 'u');
    const actionKillToEnd = mod && inp === 'k' || isMacActionFallback(k, inp, 'k');
    const actionDeleteWord = mod && inp === 'w' || isMacActionFallback(k, inp, 'w');
    const range_2 = selRange();
    const delFwd = k.delete || fwdDel.current;
    if (mod && inp === 'z') {
      return swap(undo, redo);
    }
    if (mod && inp === 'y' || mod && k.shift && inp === 'z') {
      return swap(redo, undo);
    }
    if (isMac && mod && inp === 'a') {
      return selectAll();
    }
    if (actionHome) {
      clearSel();
      c_1 = 0;
    } else if (actionEnd) {
      clearSel();
      c_1 = v_1.length;
    } else if (k.leftArrow) {
      if (range_2 && !wordMod) {
        clearSel();
        c_1 = range_2.start;
      } else {
        clearSel();
        c_1 = wordMod ? wordLeft(v_1, c_1) : prevPos(v_1, c_1);
      }
    } else if (k.rightArrow) {
      if (range_2 && !wordMod) {
        clearSel();
        c_1 = range_2.end;
      } else {
        clearSel();
        c_1 = wordMod ? wordRight(v_1, c_1) : nextPos(v_1, c_1);
      }
    } else if (wordMod && inp === 'b') {
      clearSel();
      c_1 = wordLeft(v_1, c_1);
    } else if (wordMod && inp === 'f') {
      clearSel();
      c_1 = wordRight(v_1, c_1);
    } else if (range_2 && (k.backspace || delFwd)) {
      v_1 = v_1.slice(0, range_2.start) + v_1.slice(range_2.end);
      c_1 = range_2.start;
    } else if (k.backspace && c_1 > 0) {
      if (wordMod) {
        const t = wordLeft(v_1, c_1);
        v_1 = v_1.slice(0, t) + v_1.slice(c_1);
        c_1 = t;
      } else if (canFastBackspace(v_1, c_1)) {
        const t_0 = prevPos(v_1, c_1);
        v_1 = v_1.slice(0, t_0) + v_1.slice(c_1);
        c_1 = t_0;
        stdout.write('\b \b');
        commit(v_1, c_1, true, false, false, Math.max(0, lineWidthRef.current - 1));
        return;
      } else {
        const t_1 = prevPos(v_1, c_1);
        v_1 = v_1.slice(0, t_1) + v_1.slice(c_1);
        c_1 = t_1;
      }
    } else if (delFwd && c_1 < v_1.length) {
      if (wordMod) {
        const t_2 = wordRight(v_1, c_1);
        v_1 = v_1.slice(0, c_1) + v_1.slice(t_2);
      } else {
        v_1 = v_1.slice(0, c_1) + v_1.slice(nextPos(v_1, c_1));
      }
    } else if (actionDeleteWord) {
      if (range_2) {
        v_1 = v_1.slice(0, range_2.start) + v_1.slice(range_2.end);
        c_1 = range_2.start;
      } else if (c_1 > 0) {
        clearSel();
        const t_3 = wordLeft(v_1, c_1);
        v_1 = v_1.slice(0, t_3) + v_1.slice(c_1);
        c_1 = t_3;
      } else {
        return;
      }
    } else if (actionDeleteToStart) {
      if (range_2) {
        v_1 = v_1.slice(0, range_2.start) + v_1.slice(range_2.end);
        c_1 = range_2.start;
      } else {
        v_1 = v_1.slice(c_1);
        c_1 = 0;
      }
    } else if (actionKillToEnd) {
      if (range_2) {
        v_1 = v_1.slice(0, range_2.start) + v_1.slice(range_2.end);
        c_1 = range_2.start;
      } else {
        v_1 = v_1.slice(0, c_1);
      }
    } else if (inp.length > 0) {
      const bracketed = inp.includes('[200~');
      const text_4 = inp.replace(BRACKET_PASTE, '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
      if (bracketed && emitPaste({
        bracketed: true,
        cursor: c_1,
        text: text_4,
        value: v_1
      })) {
        return;
      }
      if (!text_4) {
        return;
      }
      if (text_4 === '\n') {
        return commit(ins(v_1, c_1, '\n'), c_1 + 1);
      }
      if (text_4.length > 1 || text_4.includes('\n')) {
        if (!pasteBuf.current) {
          pastePos.current = range_2 ? range_2.start : c_1;
          pasteEnd.current = range_2 ? range_2.end : pastePos.current;
        }
        pasteBuf.current += text_4;
        if (pasteTimer.current) {
          clearTimeout(pasteTimer.current);
        }
        pasteTimer.current = setTimeout(flushPaste, 50);
        return;
      }
      if (PRINTABLE.test(text_4)) {
        if (range_2) {
          v_1 = v_1.slice(0, range_2.start) + text_4 + v_1.slice(range_2.end);
          c_1 = range_2.start + text_4.length;
        } else {
          const simpleAppend = canFastAppend(v_1, c_1, text_4);
          v_1 = v_1.slice(0, c_1) + text_4 + v_1.slice(c_1);
          c_1 += text_4.length;
          if (simpleAppend) {
            stdout.write(text_4);
            commit(v_1, c_1, true, false, false, lineWidthRef.current + stringWidth(text_4));
            return;
          }
        }
      } else {
        return;
      }
    } else {
      return;
    }
    commit(v_1, c_1);
  }, {
    isActive: focus
  });
  return {
    clearSel,
    emitPaste
  };
}