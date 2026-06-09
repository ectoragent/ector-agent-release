const KW = s => new Set(s.split(/\s+/).filter(Boolean));
const TS = KW(`
  abstract as async await break case catch class const continue debugger default delete do else enum export extends
  false finally for from function get if implements import in instanceof interface is let new null of package private
  protected public readonly return set static super switch this throw true try type typeof undefined var void while
  with yield
`);
const PY = KW(`
  False None True and as assert async await break class continue def del elif else except finally for from global if
  import in is lambda nonlocal not or pass raise return try while with yield
`);
const SH = KW(`
  if then else elif fi for in do done while until case esac function return break continue local export readonly
  declare typeset
`);
const GO = KW(`
  break case chan const continue default defer else fallthrough for func go goto if import interface map package range
  return select struct switch type var nil true false
`);
const RUST = KW(`
  as async await break const continue crate dyn else enum extern false fn for if impl in let loop match mod move mut
  pub ref return self Self static struct super trait true type unsafe use where while yield
`);
const SQL = KW(`
  select from where and or not in is null as by group order limit offset insert into values update set delete create
  table drop alter add column primary key foreign references join left right inner outer on
`);
const PHP = KW(`
  abstract and array as break callable case catch class clone const continue declare default die do echo else elseif
  empty enddeclare endfor endforeach endif endswitch endwhile enum eval exit extends final finally fn for foreach
  function global goto if implements include include_once instanceof insteadof interface isset list match namespace
  new or print private protected public readonly require require_once return static switch throw trait try unset use
  var while xor true false null
`);
const JAVA = KW(`
  abstract assert break case catch class const continue default do double else enum extends final finally float for
  if implements import instanceof int interface long native new package private protected public return short static
  strictfp super switch synchronized this throw throws transient try void volatile while true false null
`);
const RUBY = KW(`
  alias and begin break case class def defined do else elsif end ensure false for if in module next nil not or redo
  rescue retry return self super then true undef unless until when while yield
`);
const CPP = KW(`
  alignas alignof and and_eq asm auto bitand bitor bool break case catch char char8_t char16_t char32_t class compl
  concept const consteval constexpr constinit const_cast continue co_await co_return co_yield decltype default delete
  do double dynamic_cast else enum explicit export extern false float for friend goto if inline int long mutable
  namespace new noexcept not not_eq nullptr operator or or_eq private protected public register reinterpret_cast
  requires return short signed sizeof static static_assert static_cast struct switch template this thread_local
  throw true try typedef typeid typename union unsigned using virtual void volatile wchar_t while xor xor_eq
`);
const CSS = KW(`
  and atcharset important in not or url
`);
const HTML = KW(`
  true false
`);
const GENERIC = KW('');
const LANGS = {
  c: {
    comment: '//',
    keywords: CPP
  },
  cpp: {
    comment: '//',
    keywords: CPP
  },
  css: {
    comment: null,
    keywords: CSS
  },
  generic: {
    comment: null,
    keywords: GENERIC
  },
  go: {
    comment: '//',
    keywords: GO
  },
  html: {
    comment: null,
    keywords: HTML
  },
  java: {
    comment: '//',
    keywords: JAVA
  },
  json: {
    comment: null,
    keywords: KW('true false null')
  },
  kt: {
    comment: '//',
    keywords: JAVA
  },
  kotlin: {
    comment: '//',
    keywords: JAVA
  },
  php: {
    comment: ['//', '#'],
    keywords: PHP,
    variables: true
  },
  py: {
    comment: '#',
    keywords: PY
  },
  ruby: {
    comment: '#',
    keywords: RUBY
  },
  rust: {
    comment: '//',
    keywords: RUST
  },
  sh: {
    comment: '#',
    keywords: SH
  },
  sql: {
    comment: '--',
    keywords: SQL
  },
  ts: {
    comment: '//',
    keywords: TS
  },
  xml: {
    comment: null,
    keywords: HTML
  },
  yaml: {
    comment: '#',
    keywords: KW('true false null yes no on off')
  }
};
const ALIAS = {
  bash: 'sh',
  'c++': 'cpp',
  csharp: 'ts',
  cs: 'ts',
  docker: 'sh',
  dockerfile: 'sh',
  htm: 'html',
  javascript: 'ts',
  js: 'ts',
  jsx: 'ts',
  makefile: 'sh',
  perl: 'sh',
  pl: 'sh',
  python: 'py',
  rb: 'ruby',
  rs: 'rust',
  shell: 'sh',
  svg: 'xml',
  text: 'generic',
  plaintext: 'generic',
  txt: 'generic',
  tsx: 'ts',
  typescript: 'ts',
  yml: 'yaml',
  zsh: 'sh'
};
const canonicalLang = lang => {
  const key = lang.trim().toLowerCase().split(/\s+/)[0] ?? '';
  return key ? ALIAS[key] ?? key : 'generic';
};
const resolve = lang => {
  const key = lang.trim().toLowerCase().split(/\s+/)[0] ?? '';
  if (!key) {
    return null;
  }
  return LANGS[ALIAS[key] ?? key] ?? null;
};
const commentPrefixes = spec => {
  if (spec.comment == null) {
    return [];
  }
  return Array.isArray(spec.comment) ? spec.comment : [spec.comment];
};
const isCommentLine = (line, spec) => {
  const trimmed = line.trimStart();
  return commentPrefixes(spec).some(prefix => trimmed.startsWith(prefix));
};
export const isHighlightable = lang => {
  const key = lang.trim().toLowerCase().split(/\s+/)[0] ?? '';
  return Boolean(key && LANGS[ALIAS[key] ?? key]);
};
/** Linguagem efetiva para highlight em fences (desconhecidas → `generic`). */
export const resolveFenceHighlightLang = lang => {
  const key = lang.trim().toLowerCase().split(/\s+/)[0] ?? '';
  if (!key) {
    return 'generic';
  }
  if (key === 'diff' || ['md', 'markdown'].includes(key)) {
    return key;
  }
  return LANGS[ALIAS[key] ?? key] ? ALIAS[key] ?? key : 'generic';
};
const TOKEN_RE = /'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|`(?:[^`\\]|\\.)*`|\b\d+(?:\.\d+)?\b|[A-Za-z_$][\w$]*/g;
export function highlightLine(line, lang, t, tone = 'body') {
  const fence = tone === 'fence';
  const spec = resolve(lang) ?? (fence ? LANGS.generic : null);
  const c = t.color;
  const stringColor = fence ? c.codeString : c.cyan;
  const keywordColor = fence ? c.codeKeyword : c.label;
  const numberColor = fence ? c.codeNumber : c.text;
  const plainColor = fence ? c.codeFg : '';
  const boolColor = fence ? c.codeKeyword : keywordColor;
  const variableColor = fence ? c.codeLangLabel : plainColor;
  if (!spec) {
    return fence ? [[c.codeFg, line]] : [['', line]];
  }
  if (isCommentLine(line, spec)) {
    return [[fence ? c.codeComment : c.dim, line]];
  }
  const tokens = [];
  let last = 0;
  for (const m of line.matchAll(TOKEN_RE)) {
    const start = m.index ?? 0;
    if (start > last) {
      tokens.push([plainColor, line.slice(last, start)]);
    }
    const tok = m[0];
    const ch = tok[0];
    if (ch === '"' || ch === "'" || ch === '`') {
      tokens.push([stringColor, tok]);
    } else if (ch >= '0' && ch <= '9') {
      tokens.push([numberColor, tok]);
    } else if (spec.keywords.has(tok)) {
      tokens.push([boolColor, tok]);
    } else if (fence && spec.variables && tok.startsWith('$')) {
      tokens.push([variableColor, tok]);
    } else {
      tokens.push([plainColor, tok]);
    }
    last = start + tok.length;
  }
  if (last < line.length) {
    tokens.push([plainColor, line.slice(last)]);
  }
  return tokens;
}