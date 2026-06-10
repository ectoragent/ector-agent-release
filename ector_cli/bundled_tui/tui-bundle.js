// src/runtime.ts
import { EventEmitter } from "node:events";
var renderer = null;
var rootRender = null;
var rootUnmount = null;
var exitOnCtrlC = true;
var mouseTracking = true;
var inputEmitter = new EventEmitter();
var getRenderer = () => renderer;
var setRenderer = (r) => {
  renderer = r;
};
var getRootRender = () => rootRender;
var getRootUnmount = () => rootUnmount;
var setRootHandlers = (render2, unmount) => {
  rootRender = render2;
  rootUnmount = unmount;
};
var getExitOnCtrlC = () => exitOnCtrlC;
var setExitOnCtrlC = (v) => {
  exitOnCtrlC = v;
};
var getMouseTracking = () => mouseTracking;
var setMouseTracking = (v) => {
  mouseTracking = v;
};
var emitInput = (event) => {
  inputEmitter.emit("input", event);
};

// src/components/AlternateScreen/AlternateScreen.tsx
import { Fragment, jsx } from "@opentui/react/jsx-runtime";
function AlternateScreen({ children, mouseTracking: mouseTracking2 }) {
  void (mouseTracking2 ?? getMouseTracking());
  return /* @__PURE__ */ jsx(Fragment, { children });
}

// src/components/Ansi/Ansi.tsx
import { memo } from "react";

// src/components/Text/Text.tsx
import { TextAttributes as TextAttributes2 } from "@opentui/core";
import { forwardRef } from "react";

// src/coerceTextChildren.ts
import { Children, isValidElement } from "react";
function plainTextFromChildren(children) {
  if (children == null || typeof children === "boolean") {
    return "";
  }
  if (typeof children === "string" || typeof children === "number") {
    return String(children);
  }
  if (Array.isArray(children)) {
    let out = "";
    for (const child of children) {
      const part = plainTextFromChildren(child);
      if (part === null) {
        return null;
      }
      out += part;
    }
    return out;
  }
  return null;
}
function childrenNeedLayout(children) {
  return plainTextFromChildren(children) === null && children != null && children !== false;
}
function layoutTextChildren(children, keyPrefix = "t") {
  return Children.toArray(children).flatMap((child, i) => {
    if (child == null || typeof child === "boolean") {
      return [];
    }
    if (typeof child === "string" || typeof child === "number") {
      return [String(child)];
    }
    if (isValidElement(child)) {
      return [child];
    }
    if (Array.isArray(child)) {
      return layoutTextChildren(child, `${keyPrefix}-${i}`);
    }
    return [];
  });
}

// src/layoutTextSpans.tsx
import { TextAttributes } from "@opentui/core";
import { jsx as jsx2 } from "@opentui/react/jsx-runtime";
var spanAttributes = (props) => {
  let attributes = 0;
  if (props.bold) {
    attributes |= TextAttributes.BOLD;
  }
  if (props.italic) {
    attributes |= TextAttributes.ITALIC;
  }
  if (props.underline) {
    attributes |= TextAttributes.UNDERLINE;
  }
  if (props.strikethrough) {
    attributes |= TextAttributes.STRIKETHROUGH;
  }
  if (props.dim || props.dimColor) {
    attributes |= TextAttributes.DIM;
  }
  return attributes || void 0;
};
var unwrappedToSpan = (item, defaultFg, key) => {
  const { backgroundColor, color } = item.style;
  const attrs = spanAttributes(item.style);
  const spanProps = {
    ...color ? { fg: color } : { fg: defaultFg },
    ...backgroundColor && !color ? { fg: backgroundColor } : {},
    ...attrs ? { attributes: attrs } : {}
  };
  return /* @__PURE__ */ jsx2("span", { ...spanProps, children: item.text }, key);
};

// src/layoutTextSpansCore.ts
import { Children as Children2, isValidElement as isValidElement2 } from "react";
var PUA_PH_RE = /\uE100[cb]\d+\uE101/g;
var sanitizeSpanText = (text) => text.replace(PUA_PH_RE, "");
var isLinkElement = (el) => typeof el.props.url === "string";
var isTextElement = (el) => "children" in el.props && !("url" in el.props);
var unwrapTextChain = (node) => {
  if (node == null || typeof node === "boolean") {
    return null;
  }
  if (typeof node === "string" || typeof node === "number") {
    return { style: {}, text: sanitizeSpanText(String(node)) };
  }
  if (!isValidElement2(node)) {
    return null;
  }
  if (isLinkElement(node)) {
    const plain = plainTextFromChildren(node.props.children);
    if (plain === null) {
      return null;
    }
    return {
      linkUrl: node.props.url,
      style: { color: "#00B8E6", underline: true },
      text: sanitizeSpanText(plain)
    };
  }
  if (isTextElement(node)) {
    const inner = unwrapTextChain(node.props.children);
    if (!inner) {
      return null;
    }
    return {
      linkUrl: inner.linkUrl,
      style: { ...inner.style, ...node.props },
      text: sanitizeSpanText(inner.text)
    };
  }
  return null;
};
var extractPlainTextDeep = (node) => {
  if (node == null || typeof node === "boolean") {
    return "";
  }
  if (typeof node === "string" || typeof node === "number") {
    return sanitizeSpanText(String(node));
  }
  if (Array.isArray(node)) {
    return node.map(extractPlainTextDeep).join("");
  }
  if (!isValidElement2(node)) {
    return "";
  }
  if (isLinkElement(node)) {
    return extractPlainTextDeep(node.props.children);
  }
  return extractPlainTextDeep(node.props.children);
};
var flattenTextParts = (node) => {
  const direct = unwrapTextChain(node);
  if (direct) {
    return [direct];
  }
  if (isValidElement2(node) && isTextElement(node)) {
    return Children2.toArray(node.props.children).flatMap((child) => flattenTextParts(child));
  }
  const plain = plainTextFromChildren(node);
  if (plain !== null && plain.length > 0) {
    return [{ style: {}, text: sanitizeSpanText(plain) }];
  }
  return [];
};

// src/components/Text/Text.tsx
import { jsx as jsx3 } from "@opentui/react/jsx-runtime";
var textAttributes = ({
  bold,
  dim,
  dimColor,
  italic,
  strikethrough,
  underline
}) => {
  let attributes = 0;
  if (bold) {
    attributes |= TextAttributes2.BOLD;
  }
  if (italic) {
    attributes |= TextAttributes2.ITALIC;
  }
  if (underline) {
    attributes |= TextAttributes2.UNDERLINE;
  }
  if (strikethrough) {
    attributes |= TextAttributes2.STRIKETHROUGH;
  }
  if (dim || dimColor) {
    attributes |= TextAttributes2.DIM;
  }
  return attributes || void 0;
};
var wrapMode = (wrap) => {
  if (!wrap || wrap === "wrap" || wrap === "wrap-trim") {
    return "word";
  }
  return void 0;
};
var Text = forwardRef(function Text2(props, ref) {
  const { children, color, backgroundColor, wrap } = props;
  const plain = plainTextFromChildren(children);
  const attrs = textAttributes(props);
  const defaultFg = color ?? "#EEEBE7";
  const textProps = {
    fg: defaultFg,
    ...backgroundColor ? { bg: backgroundColor } : {},
    ...attrs ? { attributes: attrs } : {},
    ...wrapMode(wrap) ? { wrapMode: wrapMode(wrap) } : {},
    ...wrap === "truncate" || wrap === "truncate-end" ? { truncate: true } : {}
  };
  if (plain !== null) {
    return /* @__PURE__ */ jsx3("text", { ref, ...textProps, children: plain });
  }
  if (!childrenNeedLayout(children)) {
    return /* @__PURE__ */ jsx3("text", { ref, ...textProps, children: "" });
  }
  const parts = layoutTextChildren(children);
  const runs = parts.flatMap((part) => flattenTextParts(part)).filter((item) => item.text.length > 0);
  const spans = runs.map((item, j) => unwrappedToSpan(item, defaultFg, `ps-${j}`));
  if (!spans.length) {
    const fallback = parts.map((part) => extractPlainTextDeep(part)).join("");
    return /* @__PURE__ */ jsx3("text", { ref, ...textProps, children: fallback });
  }
  const wrapProps = wrapMode(wrap) ? { wrapMode: wrapMode(wrap) } : {};
  return /* @__PURE__ */ jsx3("text", { ref, ...wrapProps, children: spans });
});
var Text_default = Text;

// src/components/Ansi/Ansi.tsx
import { jsx as jsx4 } from "@opentui/react/jsx-runtime";
var SGR_RE = /\u001b\[([0-9;]*)m/g;
var parseSgr = (code, state) => {
  const next = { ...state };
  if (!code) {
    return { bold: false, dim: false };
  }
  for (const part of code.split(";")) {
    const n = Number(part);
    if (Number.isNaN(n)) {
      continue;
    }
    if (n === 0) {
      return { bold: false, dim: false };
    }
    if (n === 1) {
      next.bold = true;
    }
    if (n === 2) {
      next.dim = true;
    }
    if (n >= 30 && n <= 37) {
      const palette = ["#000000", "#cd3131", "#0dbc79", "#e5e510", "#2478c8", "#bc3fbc", "#11a8cd", "#e5e5e5"];
      next.fg = palette[n - 30];
    }
    if (n >= 90 && n <= 97) {
      const palette = ["#666666", "#f14c4c", "#23d18b", "#f5f543", "#3b8eea", "#d670d6", "#29b8db", "#ffffff"];
      next.fg = palette[n - 90];
    }
  }
  return next;
};
var parseAnsi = (raw) => {
  const spans = [];
  let state = { bold: false, dim: false };
  let last = 0;
  let m;
  SGR_RE.lastIndex = 0;
  while (m = SGR_RE.exec(raw)) {
    if (m.index > last) {
      spans.push({ text: raw.slice(last, m.index), ...state });
    }
    state = parseSgr(m[1] ?? "", state);
    last = m.index + m[0].length;
  }
  if (last < raw.length) {
    spans.push({ text: raw.slice(last), ...state });
  }
  return spans.filter((s) => s.text.length > 0);
};
var Ansi = memo(function Ansi2({ children, dimColor }) {
  if (typeof children !== "string") {
    return /* @__PURE__ */ jsx4(Text_default, { dim: dimColor, children: String(children ?? "") });
  }
  if (!children.includes("\x1B")) {
    return /* @__PURE__ */ jsx4(Text_default, { dim: dimColor, children });
  }
  const spans = parseAnsi(children);
  return /* @__PURE__ */ jsx4("text", { children: spans.map((s, i) => /* @__PURE__ */ jsx4("span", { fg: s.color ?? (dimColor ? "#B8B2AC" : "#EEEBE7"), children: s.text }, i)) });
});

// src/components/Box/Box.tsx
import { forwardRef as forwardRef2 } from "react";

// src/normalizeLayoutChildren.tsx
import { Children as Children3, cloneElement, Fragment as Fragment2, isValidElement as isValidElement3 } from "react";
import { jsx as jsx5 } from "@opentui/react/jsx-runtime";
var LAYOUT_TEXT_FG = "#EEEBE7";
var layoutText = (text, key) => /* @__PURE__ */ jsx5("text", { fg: LAYOUT_TEXT_FG, children: String(text) }, key);
var flattenLayoutChildren = (children, keyPrefix = "layout") => {
  const out = [];
  let i = 0;
  const walk = (node) => {
    if (node == null || typeof node === "boolean") {
      return;
    }
    if (typeof node === "string" || typeof node === "number") {
      out.push(layoutText(node, `${keyPrefix}-t-${i++}`));
      return;
    }
    if (Array.isArray(node)) {
      for (const item of node) {
        walk(item);
      }
      return;
    }
    if (isValidElement3(node) && node.type === Fragment2) {
      walk(node.props.children);
      return;
    }
    const key = node.key ?? `${keyPrefix}-n-${i++}`;
    out.push(isValidElement3(node) ? cloneElement(node, { key }) : node);
  };
  Children3.forEach(children, walk);
  return out;
};
function normalizeLayoutChildren(children) {
  return flattenLayoutChildren(children);
}

// src/openTuiLayout.ts
var INK_BORDER = {
  bold: "heavy",
  double: "double",
  round: "round",
  single: "light"
};
var assign = (out, key, value) => {
  if (value != null) {
    out[key] = value;
  }
};
var legacyLayoutToNative = (props) => {
  const out = {};
  assign(out, "flexDirection", props.flexDirection);
  assign(out, "flexGrow", props.flexGrow);
  assign(out, "flexShrink", props.flexShrink);
  assign(out, "flexWrap", props.flexWrap);
  assign(out, "height", props.height);
  assign(out, "width", props.width);
  assign(out, "minWidth", props.minWidth);
  assign(out, "minHeight", props.minHeight);
  assign(out, "maxWidth", props.maxWidth);
  assign(out, "maxHeight", props.maxHeight);
  assign(out, "alignItems", props.alignItems);
  assign(out, "alignSelf", props.alignSelf);
  assign(out, "justifyContent", props.justifyContent);
  assign(out, "columnGap", props.columnGap);
  assign(out, "rowGap", props.rowGap);
  assign(out, "position", props.position);
  assign(out, "top", props.top);
  assign(out, "right", props.right);
  assign(out, "bottom", props.bottom);
  assign(out, "left", props.left);
  assign(out, "overflow", props.overflow);
  assign(out, "opacity", props.opacity);
  assign(out, "backgroundColor", props.backgroundColor);
  assign(out, "borderColor", props.borderColor ?? props.borderLeftColor);
  const borderSides = [];
  if (props.borderTop) {
    borderSides.push("top");
  }
  if (props.borderRight) {
    borderSides.push("right");
  }
  if (props.borderBottom) {
    borderSides.push("bottom");
  }
  if (props.borderLeft) {
    borderSides.push("left");
  }
  if (borderSides.length > 0) {
    out.border = borderSides.length === 4 ? true : borderSides;
  }
  if (props.flexGrow != null && props.flexGrow > 0 && props.minHeight == null) {
    out.minHeight = 0;
  }
  const padX = props.paddingX ?? props.padding;
  const padY = props.paddingY ?? props.padding;
  if (padX != null) {
    assign(out, "paddingLeft", padX);
    assign(out, "paddingRight", padX);
  }
  if (padY != null) {
    assign(out, "paddingTop", padY);
    assign(out, "paddingBottom", padY);
  }
  assign(out, "paddingLeft", props.paddingLeft);
  assign(out, "paddingRight", props.paddingRight);
  assign(out, "paddingTop", props.paddingTop);
  assign(out, "paddingBottom", props.paddingBottom);
  assign(out, "marginTop", props.marginTop);
  assign(out, "marginBottom", props.marginBottom);
  assign(out, "marginLeft", props.marginLeft);
  assign(out, "marginRight", props.marginRight);
  if (props.borderStyle) {
    out.borderStyle = INK_BORDER[props.borderStyle] ?? props.borderStyle;
    if (borderSides.length === 0) {
      out.border = true;
    }
  }
  return out;
};

// src/components/Box/Box.tsx
import { jsx as jsx6 } from "@opentui/react/jsx-runtime";
var mapMouse = (e) => ({
  cellIsBlank: false,
  ctrlKey: Boolean(e.ctrl),
  localCol: e.col,
  localRow: e.row,
  shiftKey: Boolean(e.shift)
});
var Box = forwardRef2(function Box2({ children, onClick, onMouseDown, onMouseUp, style: styleProp, ...rest }, ref) {
  const native = legacyLayoutToNative(rest);
  const mouseProps = onClick || onMouseDown || onMouseUp ? {
    onMouseDown: onMouseDown ? (e) => onMouseDown(mapMouse(e)) : void 0,
    onMouseUp: onClick ? (e) => {
      if (e.button === 0) {
        onClick(mapMouse(e));
      }
    } : onMouseUp ? () => onMouseUp() : void 0
  } : {};
  return /* @__PURE__ */ jsx6("box", { ref, ...native, style: styleProp, ...mouseProps, children: normalizeLayoutChildren(children) });
});
var Box_default = Box;

// src/components/Link/Link.tsx
import { jsx as jsx7 } from "@opentui/react/jsx-runtime";
function Link({ children, url }) {
  const plain = plainTextFromChildren(children);
  return /* @__PURE__ */ jsx7("a", { href: url, children: plain !== null ? /* @__PURE__ */ jsx7("span", { fg: "#00B8E6", children: /* @__PURE__ */ jsx7("u", { children: plain }) }) : flattenLayoutChildren(children, "link") });
}

// src/components/Newline/Newline.tsx
import { jsx as jsx8 } from "@opentui/react/jsx-runtime";
function Newline() {
  return /* @__PURE__ */ jsx8("br", {});
}

// src/components/NoSelect/NoSelect.tsx
import { jsx as jsx9 } from "@opentui/react/jsx-runtime";
function NoSelect({ children, fromLeftEdge: _fromLeftEdge, ...props }) {
  return /* @__PURE__ */ jsx9(Box_default, { ...props, children });
}

// src/lib/scrollMath.ts
var BOTTOM_SLACK = 2;
var MANUAL_SCROLL_GRACE_MS = 2500;
var maxScrollTop = (scrollHeight, viewportHeight) => Math.max(0, scrollHeight - viewportHeight);
var isNearScrollBottom = (scrollTop, scrollHeight, viewportHeight, slack = BOTTOM_SLACK) => scrollTop >= maxScrollTop(scrollHeight, viewportHeight) - slack;

// src/components/ScrollBox/ScrollBox.tsx
import { forwardRef as forwardRef3, useEffect, useImperativeHandle, useRef } from "react";
import { jsx as jsx10 } from "@opentui/react/jsx-runtime";
var scrollViewportHeight = (sb) => {
  if (!sb) {
    return 0;
  }
  const vh = sb.viewport?.height ?? 0;
  if (vh > 0) {
    return vh;
  }
  if (sb.height > 0) {
    return sb.height;
  }
  const renderer2 = getRenderer();
  const termH = renderer2?.terminalHeight ?? process.stdout.rows ?? 24;
  return Math.max(6, termH - 10);
};
var syncStickyScroll = (sb, manualAt, lastScrollHeight) => {
  const viewH = scrollViewportHeight(sb);
  const maxTop = maxScrollTop(sb.scrollHeight, viewH);
  const grew = sb.scrollHeight > lastScrollHeight.current + 0.5;
  lastScrollHeight.current = sb.scrollHeight;
  if (viewH <= 0) {
    return sb.stickyScroll;
  }
  const manualGrace = manualAt > 0 && Date.now() - manualAt < MANUAL_SCROLL_GRACE_MS;
  const historySlack = Math.max(4, viewH >> 2);
  const readingHistory = sb.scrollTop < maxTop - historySlack;
  if (manualGrace || readingHistory) {
    sb.stickyScroll = false;
    return false;
  }
  if (sb.stickyScroll && grew && isNearScrollBottom(sb.scrollTop, sb.scrollHeight, viewH) && sb.scrollTop < maxTop - 1) {
    sb.scrollTo(maxTop);
  }
  return sb.stickyScroll;
};
var ScrollBox = forwardRef3(function ScrollBox2({ children, stickyScroll, style: styleProp, ...rest }, ref) {
  const innerRef = useRef(null);
  const stickyPropRef = useRef(stickyScroll ?? true);
  stickyPropRef.current = stickyScroll ?? true;
  const listenersRef = useRef(/* @__PURE__ */ new Set());
  const clampRef = useRef({});
  const pendingRef = useRef(0);
  const manualAtRef = useRef(0);
  const lastViewportHRef = useRef(0);
  const lastScrollHeightRef = useRef(0);
  const notify = () => {
    for (const l of listenersRef.current) {
      l();
    }
  };
  useEffect(() => {
    const sb = innerRef.current;
    if (sb?.verticalScrollBar) {
      sb.verticalScrollBar.visible = false;
    }
    if (sb?.horizontalScrollBar) {
      sb.horizontalScrollBar.visible = false;
    }
  }, []);
  useEffect(() => {
    const renderer2 = getRenderer();
    if (!renderer2?.setFrameCallback) {
      return;
    }
    let lastTop = innerRef.current?.scrollTop ?? -1;
    let lastScrollH = innerRef.current?.scrollHeight ?? -1;
    const onFrame = async () => {
      const sb = innerRef.current;
      if (sb) {
        const vh = scrollViewportHeight(sb);
        if (vh > 0 && lastViewportHRef.current === 0) {
          lastViewportHRef.current = vh;
          notify();
        } else if (vh > 0 && vh !== lastViewportHRef.current) {
          lastViewportHRef.current = vh;
          notify();
        }
        syncStickyScroll(sb, manualAtRef.current, lastScrollHeightRef);
      }
      if (listenersRef.current.size === 0) {
        return;
      }
      const top = sb?.scrollTop ?? 0;
      const scrollH = sb?.scrollHeight ?? 0;
      if (top !== lastTop || scrollH !== lastScrollH) {
        lastTop = top;
        lastScrollH = scrollH;
        notify();
      }
    };
    renderer2.setFrameCallback(onFrame);
    return () => renderer2.removeFrameCallback?.(onFrame);
  }, []);
  useImperativeHandle(
    ref,
    () => ({
      getFreshScrollHeight: () => innerRef.current?.scrollHeight ?? 0,
      getLastManualScrollAt: () => manualAtRef.current,
      getPendingDelta: () => pendingRef.current,
      getScrollHeight: () => innerRef.current?.scrollHeight ?? 0,
      getScrollTop: () => innerRef.current?.scrollTop ?? 0,
      getViewportHeight: () => scrollViewportHeight(innerRef.current),
      getViewportTop: () => 0,
      isSticky: () => innerRef.current?.stickyScroll ?? stickyPropRef.current,
      scrollBy: (dy) => {
        const sb = innerRef.current;
        if (!sb) {
          return;
        }
        pendingRef.current += dy;
        clampRef.current = {};
        sb.scrollBy(dy);
        const viewH = scrollViewportHeight(sb);
        if (dy < 0) {
          sb.stickyScroll = false;
          manualAtRef.current = Date.now();
        } else if (isNearScrollBottom(sb.scrollTop, sb.scrollHeight, viewH)) {
          sb.stickyScroll = true;
          manualAtRef.current = 0;
        } else {
          sb.stickyScroll = false;
          manualAtRef.current = Date.now();
        }
        syncStickyScroll(sb, manualAtRef.current, lastScrollHeightRef);
        queueMicrotask(() => {
          pendingRef.current = 0;
          notify();
        });
      },
      scrollTo: (y) => {
        const sb = innerRef.current;
        if (!sb) {
          return;
        }
        let target = Math.max(0, y);
        const { min, max } = clampRef.current;
        if (min != null) {
          target = Math.max(min, target);
        }
        if (max != null) {
          target = Math.min(max, target);
        }
        sb.scrollTo(target);
        const viewH = scrollViewportHeight(sb);
        const docked = isNearScrollBottom(target, sb.scrollHeight, viewH);
        if (docked) {
          sb.stickyScroll = true;
          manualAtRef.current = 0;
        } else {
          sb.stickyScroll = false;
          manualAtRef.current = Date.now();
        }
        pendingRef.current = 0;
        notify();
      },
      scrollToBottom: () => {
        const sb = innerRef.current;
        if (!sb) {
          return;
        }
        clampRef.current = {};
        const viewH = scrollViewportHeight(sb);
        const target = Math.max(0, sb.scrollHeight - viewH);
        sb.stickyScroll = true;
        manualAtRef.current = 0;
        if (sb.scrollTop >= target - 1) {
          pendingRef.current = 0;
          notify();
          return;
        }
        sb.scrollTo(target);
        pendingRef.current = 0;
        notify();
      },
      scrollToElement: () => {
      },
      setClampBounds: (min, max) => {
        clampRef.current = { min, max };
      },
      subscribe: (listener) => {
        listenersRef.current.add(listener);
        return () => listenersRef.current.delete(listener);
      }
    }),
    []
  );
  const native = legacyLayoutToNative(rest);
  return /* @__PURE__ */ jsx10(
    "scrollbox",
    {
      horizontalScrollbarOptions: { visible: false },
      ref: innerRef,
      stickyScroll: false,
      verticalScrollbarOptions: { visible: false },
      viewportCulling: false,
      ...native,
      style: styleProp,
      children: normalizeLayoutChildren(children)
    }
  );
});
var ScrollBox_default = ScrollBox;

// src/components/Spacer/Spacer.tsx
import { jsx as jsx11 } from "@opentui/react/jsx-runtime";
function Spacer() {
  return /* @__PURE__ */ jsx11(Box_default, { flexGrow: 1 });
}

// src/terminalShutdown.ts
var TERMINAL_RESTORE_SEQ = "\x1B[?1000l\x1B[?1002l\x1B[?1003l\x1B[?1006l\x1B[?2004l\x1B[?25h\x1B[?1049l\x1B[0m";
var shuttingDown = false;
function shutdownTui() {
  if (shuttingDown) {
    return;
  }
  shuttingDown = true;
  const renderer2 = getRenderer();
  try {
    getRootUnmount()?.();
  } catch {
  }
  try {
    if (renderer2 && !renderer2.isDestroyed) {
      renderer2.destroy();
    }
  } catch {
  }
  setRenderer(null);
  setRootHandlers(null, null);
  try {
    process.stdin.setRawMode?.(false);
  } catch {
  }
  if (process.stdout.isTTY) {
    try {
      process.stdout.write(TERMINAL_RESTORE_SEQ);
    } catch {
    }
  }
}

// src/hooks/useApp.ts
function useApp() {
  return {
    exit: (error) => {
      shutdownTui();
      if (error) {
        process.stderr.write(`${error.stack ?? error.message}
`);
      }
      process.exit(error ? 1 : 0);
    },
    // Ink rerender hook — no-op; React root owns updates.
    rerender: () => {
      void getRootRender();
    }
  };
}

// src/hooks/useDeclaredCursor.ts
import { useEffect as useEffect2, useRef as useRef2 } from "react";
function useDeclaredCursor(args) {
  const elRef = useRef2(null);
  const argsRef = useRef2(args);
  argsRef.current = args;
  const styleKeyRef = useRef2("");
  useEffect2(() => {
    const apply = () => {
      const renderer3 = getRenderer();
      const box = elRef.current;
      const { line, column, active, style = "line" } = argsRef.current;
      if (!renderer3?.setCursorPosition || !box) {
        return;
      }
      const x = box.screenX + column + 1;
      const y = box.screenY + line + 1;
      renderer3.setCursorPosition(x, y, active);
      if (renderer3.setCursorStyle) {
        const styleKey = `${active}:${style}`;
        if (styleKeyRef.current !== styleKey) {
          styleKeyRef.current = styleKey;
          renderer3.setCursorStyle({
            blinking: active,
            style: active ? style : "default"
          });
        }
      }
    };
    apply();
    const renderer2 = getRenderer();
    if (!renderer2?.setFrameCallback) {
      return () => {
        styleKeyRef.current = "";
        renderer2?.setCursorPosition?.(0, 0, false);
        renderer2?.setCursorStyle?.({ blinking: false, style: "default" });
      };
    }
    renderer2.setFrameCallback(apply);
    return () => {
      styleKeyRef.current = "";
      renderer2.removeFrameCallback?.(apply);
      renderer2.setCursorPosition?.(0, 0, false);
      renderer2.setCursorStyle?.({ blinking: false, style: "default" });
    };
  }, [args.active, args.column, args.line, args.style]);
  return (el) => {
    elRef.current = el;
  };
}

// src/hooks/useExternalProcess.ts
import { useCallback } from "react";
var HANDOFF = `${TERMINAL_RESTORE_SEQ}\x1B[2J\x1B[H`;
var RESTORE_MOUSE = "\x1B[?1000h\x1B[?1002h\x1B[?1003h\x1B[?25l";
async function withInkSuspended(run) {
  const r = getRenderer();
  r?.pause?.();
  process.stdin.setRawMode?.(false);
  process.stdout.write(HANDOFF);
  try {
    await run();
  } finally {
    process.stdout.write(RESTORE_MOUSE);
    process.stdin.setRawMode?.(true);
    r?.resume?.();
    void getMouseTracking();
  }
}
function useExternalProcess() {
  return useCallback((run) => withInkSuspended(run), []);
}

// src/hooks/useInput.ts
import { useEffect as useEffect3, useLayoutEffect } from "react";

// src/hooks/useStdin.ts
import { useMemo } from "react";
function useStdin() {
  return useMemo(
    () => ({
      exitOnCtrlC: false,
      inputEmitter,
      isRawModeSupported: true,
      querier: null,
      setRawMode: (_value) => {
      },
      stdin: process.stdin
    }),
    []
  );
}

// src/hooks/useInput.ts
function useInput(inputHandler, options = {}) {
  const { exitOnCtrlC: exitOnCtrlC2 } = useStdin();
  useLayoutEffect(() => {
    if (options.isActive === false) {
      return;
    }
  }, [options.isActive]);
  useEffect3(() => {
    if (options.isActive === false) {
      return;
    }
    const handle = (event) => {
      const { input, key } = event;
      if (!(input === "c" && key.ctrl) || !exitOnCtrlC2) {
        inputHandler(input, key, event);
      }
    };
    inputEmitter.on("input", handle);
    return () => {
      inputEmitter.off("input", handle);
    };
  }, [exitOnCtrlC2, inputHandler, options.isActive]);
}

// src/hooks/useSelection.ts
import { useRef as useRef3 } from "react";

// src/lib/systemClipboard.ts
import { spawnSync } from "node:child_process";
import { closeSync, openSync, writeSync } from "node:fs";
var POWERSHELL_SET_CLIPBOARD = [
  "-NoProfile",
  "-NonInteractive",
  "-Command",
  "$input | Set-Clipboard"
];
var isRemoteShell = (env = process.env) => Boolean(env.SSH_CONNECTION || env.SSH_CLIENT || env.SSH_TTY);
var forceOsc52 = (env = process.env) => /^(?:1|true|yes|on)$/i.test((env.ECTOR_TUI_FORCE_OSC52 ?? "").trim());
function writeClipboardCommands(platform, env) {
  if (platform === "darwin") {
    return [{ cmd: "pbcopy", args: [] }];
  }
  if (platform === "win32") {
    return [{ cmd: "powershell", args: POWERSHELL_SET_CLIPBOARD }];
  }
  const attempts = [];
  if (env.WSL_INTEROP) {
    attempts.push({ cmd: "powershell.exe", args: POWERSHELL_SET_CLIPBOARD });
  }
  if (env.WAYLAND_DISPLAY) {
    attempts.push({ cmd: "wl-copy", args: ["--type", "text"] });
  }
  attempts.push({ cmd: "xclip", args: ["-selection", "clipboard"] });
  return attempts;
}
function buildOsc52Sequence(text) {
  return `\x1B]52;c;${Buffer.from(text, "utf8").toString("base64")}\x07`;
}
function wrapForMultiplexer(sequence) {
  if (process.env.TMUX) {
    const esc = "\x1B";
    return `${esc}Ptmux;${sequence.split(esc).join(esc + esc)}${esc}\\`;
  }
  if (process.env.STY) {
    return `\x1BP${sequence}\x1B\\`;
  }
  return sequence;
}
function writeOsc52Clipboard(text) {
  const sequence = wrapForMultiplexer(buildOsc52Sequence(text));
  const ttyCandidates = [process.env.SSH_TTY, "/dev/tty"].filter((p) => Boolean(p));
  for (const ttyPath of ttyCandidates) {
    try {
      const fd = openSync(ttyPath, "w");
      writeSync(fd, sequence);
      closeSync(fd);
      return;
    } catch {
    }
  }
  if (process.stdout.isTTY) {
    process.stdout.write(sequence);
  }
}
function copyViaRendererOsc52(text, renderer2) {
  if (!renderer2?.copyToClipboardOSC52) {
    return false;
  }
  try {
    return Boolean(renderer2.copyToClipboardOSC52(text));
  } catch {
    return false;
  }
}
function writeClipboardTextSync(text, platform = process.platform, env = process.env) {
  for (const attempt of writeClipboardCommands(platform, env)) {
    try {
      const result = spawnSync(attempt.cmd, [...attempt.args], {
        encoding: "utf8",
        input: text,
        windowsHide: true
      });
      if (result.status === 0 && !result.error) {
        return true;
      }
    } catch {
    }
  }
  return false;
}
function copyTextToSystemClipboard(text, renderer2 = getRenderer(), env = process.env) {
  if (!text) {
    return;
  }
  if (forceOsc52(env)) {
    copyViaRendererOsc52(text, renderer2);
    writeOsc52Clipboard(text);
    return;
  }
  copyViaRendererOsc52(text, renderer2);
  if (isRemoteShell(env) || !writeClipboardTextSync(text, process.platform, env)) {
    writeOsc52Clipboard(text);
  }
}

// src/hooks/useSelection.ts
var rendererHasSelection = (r) => {
  if (!r) {
    return false;
  }
  const v = r.hasSelection;
  return typeof v === "function" ? v.call(r) : Boolean(v);
};
function useSelection() {
  const bgRef = useRef3(void 0);
  return {
    captureScrolledRows: () => {
    },
    clearSelection: () => getRenderer()?.clearSelection(),
    copySelection: async () => {
      const r = getRenderer();
      const text = r?.getSelection()?.getSelectedText() ?? "";
      if (text) {
        copyTextToSystemClipboard(text, r);
      }
      r?.clearSelection();
      return text;
    },
    copySelectionNoClear: async () => getRenderer()?.getSelection()?.getSelectedText() ?? "",
    getState: () => ({ isDragging: false }),
    hasSelection: () => rendererHasSelection(getRenderer()),
    moveFocus: () => {
    },
    setSelectionBgColor: (color) => {
      bgRef.current = color;
    },
    shiftAnchor: () => {
    },
    shiftSelection: () => {
    },
    subscribe: (cb) => {
      const r = getRenderer();
      if (!r?.setFrameCallback) {
        return () => {
        };
      }
      let had = rendererHasSelection(r);
      let armed = false;
      const onFrame = async () => {
        const has = rendererHasSelection(getRenderer());
        if (has && !had) {
          armed = true;
        }
        if (!has && had && armed) {
          armed = false;
          cb();
        }
        had = has;
      };
      r.setFrameCallback(onFrame);
      return () => r.removeFrameCallback?.(onFrame);
    }
  };
}
function useHasSelection() {
  const r = getRenderer();
  return rendererHasSelection(r);
}

// src/hooks/useStderr.ts
function useStderr() {
  return { stderr: process.stderr };
}

// src/hooks/useStdout.ts
function useStdout() {
  return { stdout: process.stdout };
}

// src/hooks/useTabStatus.ts
function useTabStatus() {
  return true;
}

// src/hooks/useTerminalFocus.ts
import { useBlur, useFocus } from "@opentui/react";
import { useState } from "react";
function useTerminalFocus() {
  const [focused, setFocused] = useState(true);
  useFocus(() => setFocused(true));
  useBlur(() => setFocused(false));
  return focused;
}

// src/hooks/useTerminalTitle.ts
import { useEffect as useEffect4 } from "react";
function useTerminalTitle(title) {
  useEffect4(() => {
    if (title) {
      process.stdout.write(`\x1B]0;${title}\x07`);
    }
  }, [title]);
}

// src/hooks/useTerminalViewport.ts
import { useCallback as useCallback2, useRef as useRef4 } from "react";
function useTerminalViewport() {
  const entryRef = useRef4({ isVisible: true });
  const setElement = useCallback2((_el) => {
  }, []);
  return [setElement, entryRef.current];
}

// src/lib/ctrlCForceQuit.ts
var FORCE_QUIT_WINDOW_MS = 1500;
var lastCtrlCAt = 0;
var forceQuitOnSecondCtrlC = (sequence) => {
  if (sequence !== "") {
    return false;
  }
  const now = Date.now();
  if (now - lastCtrlCAt < FORCE_QUIT_WINDOW_MS) {
    shutdownTui();
    process.exit(130);
  }
  lastCtrlCAt = now;
  return false;
};

// src/lib/mouseInputLeak.ts
var ESC = "\x1B";
var SGR_MOUSE_FULL_RE = new RegExp(`^${ESC}\\[<\\d+(?:;\\d+){0,2}[Mm]$`);
var SGR_MOUSE_LEAK_RE = /^(?:<)?\d+(?:;\d+){0,2}[Mm]$/;
var SGR_MOUSE_BURST_RE = /^(?:\d+;\d+;\d+[Mm]){2,}$/;
var SGR_MOUSE_FRAGMENT_RE = /\d+;\d+;\d+[Mm]/g;
var SGR_MOUSE_FRAGMENT_TEST = /\d+;\d+;\d+[Mm]/;
var isMouseInputLeak = (raw, input = "") => {
  const candidate = raw || input;
  if (!candidate) {
    return false;
  }
  return SGR_MOUSE_FULL_RE.test(candidate) || SGR_MOUSE_LEAK_RE.test(candidate) || SGR_MOUSE_BURST_RE.test(candidate) || SGR_MOUSE_FRAGMENT_TEST.test(candidate);
};
var sequenceContainsMouseLeak = (sequence) => {
  if (!sequence) {
    return false;
  }
  if (isMouseInputLeak(sequence)) {
    return true;
  }
  return SGR_MOUSE_FRAGMENT_TEST.test(sequence);
};
var stripMouseLeakFragments = (text) => {
  if (!text) {
    return text;
  }
  return text.replace(SGR_MOUSE_FRAGMENT_RE, "");
};

// src/lib/inputPipeline.ts
var createSwallowMouseSequence = (mouseParser) => {
  return (sequence) => {
    if (sequenceContainsMouseLeak(sequence) || isMouseInputLeak(sequence)) {
      return true;
    }
    return mouseParser.parseMouseEvent(Buffer.from(sequence)) !== null;
  };
};

// src/render.tsx
import { createCliRenderer, MouseParser } from "@opentui/core";
import { createRoot } from "@opentui/react";

// src/components/InputBridge/InputBridge.tsx
import { decodePasteBytes } from "@opentui/core";
import { useKeyboard, usePaste } from "@opentui/react";

// src/input.ts
var named = (e, name) => e.name === name;
var toInkKey = (e) => ({
  alt: e.option,
  backspace: named(e, "backspace"),
  ctrl: e.ctrl,
  delete: named(e, "delete"),
  downArrow: named(e, "down"),
  end: named(e, "end"),
  escape: named(e, "escape"),
  home: named(e, "home"),
  leftArrow: named(e, "left"),
  meta: e.meta,
  pageDown: named(e, "pagedown"),
  pageUp: named(e, "pageup"),
  rightArrow: named(e, "right"),
  return: named(e, "return"),
  shift: e.shift,
  super: Boolean(e.super),
  tab: named(e, "tab"),
  upArrow: named(e, "up"),
  wheelDown: false,
  wheelUp: false,
  [e.name]: true
});
var inkInputChar = (e) => {
  if (e.sequence === "") {
    return "c";
  }
  if (e.ctrl && e.name.length === 1) {
    return e.name;
  }
  if (e.sequence.length === 1 && !e.ctrl && !e.meta) {
    return e.sequence;
  }
  return "";
};
var toInputEvent = (e) => ({
  input: inkInputChar(e),
  key: toInkKey(e),
  keypress: { raw: e.raw }
});

// src/components/InputBridge/InputBridge.tsx
function InputBridge() {
  useKeyboard(
    (key) => {
      if (key.eventType === "release") {
        return;
      }
      if ((key.ctrl && key.name === "c" || key.sequence === "") && getExitOnCtrlC()) {
        shutdownTui();
        process.exit(130);
        return;
      }
      const event = toInputEvent(key);
      const raw = event.keypress.raw ?? event.input;
      if (isMouseInputLeak(raw, event.input)) {
        return;
      }
      emitInput(event);
    },
    { release: false }
  );
  usePaste((event) => {
    const text = decodePasteBytes(event.bytes);
    if (text) {
      emitInput({
        input: text,
        key: { ctrl: false, meta: false, super: false, shift: false, alt: false },
        keypress: { raw: text }
      });
    }
  });
  return null;
}

// src/hooks/useTerminalDimensions.ts
import { useAppContext } from "@opentui/react";
import { useCallback as useCallback3, useSyncExternalStore } from "react";
var readSize = (renderer2) => ({
  cols: process.stdout.columns ?? renderer2?.terminalWidth ?? 80,
  rows: process.stdout.rows ?? renderer2?.terminalHeight ?? 24
});
function useTerminalDimensions() {
  const { renderer: renderer2 } = useAppContext();
  const subscribe = useCallback3((onStoreChange) => {
    const stdout = process.stdout;
    const onResize = () => onStoreChange();
    stdout.on("resize", onResize);
    const r = getRenderer();
    r?.on?.("resize", onResize);
    return () => {
      stdout.off("resize", onResize);
      r?.off?.("resize", onResize);
    };
  }, []);
  const getSnapshot = useCallback3(() => {
    const { cols: cols2, rows: rows2 } = readSize(renderer2 ?? getRenderer());
    return `${cols2}x${rows2}`;
  }, [renderer2]);
  const snap = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  const [cols, rows] = snap.split("x").map((n) => Number.parseInt(n, 10));
  return {
    cols: Number.isFinite(cols) ? cols : 80,
    rows: Number.isFinite(rows) ? rows : 24
  };
}

// src/TerminalShell.tsx
import { jsx as jsx12 } from "@opentui/react/jsx-runtime";
function TerminalShell({ children }) {
  const { cols, rows } = useTerminalDimensions();
  return /* @__PURE__ */ jsx12("box", { backgroundColor: "#0A0A0A", flexDirection: "column", height: rows, minHeight: 0, width: cols, children: normalizeLayoutChildren(children) });
}

// src/render.tsx
import { jsx as jsx13, jsxs } from "@opentui/react/jsx-runtime";
async function render(node, options = {}) {
  setExitOnCtrlC(options.exitOnCtrlC ?? true);
  setMouseTracking(options.mouseTracking ?? true);
  const swallowMouseSequence = createSwallowMouseSequence(new MouseParser());
  const renderer2 = await createCliRenderer({
    backgroundColor: "#0A0A0A",
    enableMouseMovement: options.enableMouseMovement ?? true,
    exitOnCtrlC: options.exitOnCtrlC ?? true,
    prependInputHandlers: [forceQuitOnSecondCtrlC, swallowMouseSequence],
    screenMode: "alternate-screen",
    stdin: options.stdin,
    stdout: options.stdout,
    useMouse: options.mouseTracking ?? true
  });
  setRenderer(renderer2);
  const root = createRoot(renderer2);
  let current = node;
  const wrapped = /* @__PURE__ */ jsxs(TerminalShell, { children: [
    /* @__PURE__ */ jsx13(InputBridge, {}),
    node
  ] });
  setRootHandlers(
    (n) => {
      current = n;
      root.render(
        /* @__PURE__ */ jsxs(TerminalShell, { children: [
          /* @__PURE__ */ jsx13(InputBridge, {}),
          n
        ] })
      );
    },
    () => root.unmount()
  );
  root.render(wrapped);
  if (!renderer2.isRunning) {
    renderer2.start();
  }
  let frameStart = performance.now();
  if (options.onFrame) {
    const tick = () => {
      options.onFrame?.({ durationMs: performance.now() - frameStart });
      frameStart = performance.now();
      setImmediate(tick);
    };
    setImmediate(tick);
  }
  return {
    cleanup: () => shutdownTui(),
    rerender: (next) => {
      current = next;
      getRootRender()?.(next);
    },
    unmount: () => shutdownTui(),
    waitUntilExit: () => new Promise(() => {
    })
  };
}
var render_default = render;
var renderSync = render;

// src/stringWidth.ts
import stripAnsi from "strip-ansi";
var stringWidth = (s) => {
  let w = 0;
  for (const ch of stripAnsi(s)) {
    const code = ch.codePointAt(0) ?? 0;
    if (code >= 4352 && (code <= 4447 || code === 9001 || code === 9002)) {
      w += 2;
      continue;
    }
    if (code >= 11904 && code <= 42191 && code !== 12351 || code >= 44032 && code <= 55203 || code >= 63744 && code <= 64255 || code >= 65040 && code <= 65055 || code >= 65072 && code <= 65135 || code >= 65280 && code <= 65376 || code >= 65504 && code <= 65510 || code >= 131072 && code <= 196605 || code >= 196608 && code <= 262141) {
      w += 2;
      continue;
    }
    w += 1;
  }
  return w;
};

// src/stubs.ts
import { createElement } from "react";
var scrollFastPathStats = {
  captured: 0,
  declined: { heightDeltaMismatch: 0, noPrevScreen: 0, other: 0 },
  lastDeclineReason: void 0,
  lastHeightDelta: void 0,
  lastHintDelta: void 0,
  lastPrevHeight: void 0,
  lastScrollHeight: void 0,
  taken: 0
};
function evictInkCaches(_level) {
  return { lineWidth: 0, slice: 0, width: 0, wrap: 0 };
}
function isXtermJs() {
  const term = (process.env.TERM_PROGRAM ?? "").toLowerCase();
  return term.includes("vscode") || term.includes("cursor") || term.includes("iterm") || term === "xterm";
}
function measureElement() {
  return { height: 1, width: 80 };
}
function supportsTerminalFastEcho() {
  return false;
}
function RawAnsi({ children }) {
  return createElement(Text_default, null, children ?? "");
}

// src/entry-exports.ts
function TextInput() {
  return null;
}
export {
  AlternateScreen,
  Ansi,
  Box_default as Box,
  FORCE_QUIT_WINDOW_MS,
  Link,
  MANUAL_SCROLL_GRACE_MS,
  Newline,
  NoSelect,
  RawAnsi,
  ScrollBox_default as ScrollBox,
  Spacer,
  Text_default as Text,
  TextInput,
  copyTextToSystemClipboard,
  createSwallowMouseSequence,
  evictInkCaches,
  forceQuitOnSecondCtrlC,
  getRenderer,
  isMouseInputLeak,
  isNearScrollBottom,
  isXtermJs,
  maxScrollTop,
  measureElement,
  render_default as render,
  renderSync,
  scrollFastPathStats,
  sequenceContainsMouseLeak,
  shutdownTui,
  stringWidth,
  stripMouseLeakFragments,
  supportsTerminalFastEcho,
  useApp,
  useDeclaredCursor,
  useExternalProcess,
  useHasSelection,
  useInput,
  useSelection,
  useStderr,
  useStdin,
  useStdout,
  useTabStatus,
  useTerminalFocus,
  useTerminalTitle,
  useTerminalViewport,
  withInkSuspended,
  writeClipboardTextSync,
  writeOsc52Clipboard
};
