/**
 * Parse the human-readable description produced by
 * ``tools/approval.py::_format_tirith_description``.
 */
export function parseApprovalFindings(raw) {
  const cleaned = (raw ?? '').replace(/^(?:Security scan|Varredura de segurança)\s*[—:]\s*/i, '').trim();
  if (!cleaned) {
    return [{
      detail: 'comando potencialmente perigoso',
      severity: '',
      title: ''
    }];
  }
  const chunks = cleaned.replace(/;\s+(?=\[[^\]]+\])/g, '\u0000').split('\u0000').map(s => s.trim()).filter(Boolean);
  const findings = [];
  for (const chunk of chunks) {
    const match = /^\[(?<sev>[^\]]+)\]\s*(?<rest>.+)$/su.exec(chunk);
    if (!match?.groups) {
      findings.push({
        detail: chunk,
        severity: '',
        title: ''
      });
      continue;
    }
    const severity = match.groups.sev.trim();
    const rest = match.groups.rest.trim();
    const splitIdx = rest.indexOf(': ');
    if (splitIdx > 0) {
      findings.push({
        detail: rest.slice(splitIdx + 2).trim(),
        severity,
        title: rest.slice(0, splitIdx).trim()
      });
    } else {
      findings.push({
        detail: '',
        severity,
        title: rest
      });
    }
  }
  return findings.length ? findings : [{
    detail: cleaned,
    severity: '',
    title: ''
  }];
}