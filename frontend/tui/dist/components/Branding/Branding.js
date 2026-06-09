import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Ansi, Box, Text } from '@ector/ink';
import { formatBannerVersion } from '../../content/pixelLogo.js';
import { transcriptContentCols } from '../../domain/transcriptLayout.js';
import { BannerLogo } from '../BannerLogo/index.js';
export function Banner({
  cols,
  releaseName,
  t,
  version
}) {
  const hero = t.bannerHero.trim();
  const customLogo = t.bannerLogo.trim();
  const contentCols = transcriptContentCols(cols);
  const versionLabel = formatBannerVersion(version, releaseName);
  const composerInk = t.color.text;
  const edge = composerInk;
  const peak = composerInk;
  return _jsxs(Box, {
    flexDirection: "column",
    marginBottom: 1,
    width: contentCols,
    children: [customLogo ? customLogo.split('\n').map(line => line.trimEnd()).filter(line => line.trim().length > 0).map((line, i) => _jsx(Box, {
      justifyContent: "center",
      width: contentCols,
      children: _jsx(Ansi, {
        children: line
      })
    }, i)) : _jsx(BannerLogo, {
      contentCols: contentCols,
      edge: edge,
      peak: peak,
      rippleBlue: t.color.cyan
    }), versionLabel ? _jsx(Box, {
      justifyContent: "center",
      marginTop: 0,
      width: contentCols,
      children: _jsx(Text, {
        color: t.color.statusBarMeta,
        dim: true,
        children: versionLabel
      })
    }) : null, hero ? _jsx(Box, {
      justifyContent: "center",
      marginTop: versionLabel ? 0 : 1,
      width: contentCols,
      children: _jsx(Text, {
        bold: true,
        color: t.color.text,
        children: hero
      })
    }) : null]
  });
}
export function Panel({
  sections,
  t,
  title
}) {
  return _jsx(Box, {
    borderColor: t.color.border,
    borderStyle: "round",
    flexDirection: "column",
    paddingX: 2,
    paddingY: 1,
    children: [_jsx(Box, {
      justifyContent: "center",
      marginBottom: 1,
      children: _jsx(Text, {
        bold: true,
        color: t.color.title,
        children: title
      })
    }, "panel-title"), ...sections.map((sec, si) => _jsx(Box, {
      flexDirection: "column",
      marginTop: si > 0 ? 1 : 0,
      children: [sec.title ? _jsx(Text, {
        bold: true,
        color: t.color.cyan,
        children: sec.title
      }, `t-${si}`) : null, ...(sec.rows?.map(([k, v], ri) => _jsxs(Text, {
        wrap: "truncate",
        children: [_jsx(Text, {
          color: t.color.dim,
          children: k.padEnd(20)
        }), _jsx(Text, {
          color: t.color.text,
          children: v
        })]
      }, `r-${ri}`)) ?? []), ...(sec.items?.map((item, ii) => _jsx(Text, {
        color: t.color.text,
        wrap: "truncate",
        children: item
      }, `i-${ii}`)) ?? []), sec.text ? _jsx(Text, {
        color: t.color.dim,
        children: sec.text
      }, `x-${si}`) : null].filter(Boolean)
    }, si))]
  });
}