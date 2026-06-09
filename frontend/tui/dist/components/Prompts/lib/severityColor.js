export function severityColor(sev, t) {
  const key = sev.toUpperCase();
  if (key === 'CRITICAL' || key === 'CRÍTICA' || key === 'HIGH' || key === 'ALTA') {
    return t.color.error;
  }
  if (key === 'MEDIUM' || key === 'MÉDIA' || key === 'MEDIA' || key === 'MED' || key === 'WARN' || key === 'WARNING' || key === 'AVISO') {
    return t.color.warn;
  }
  if (key === 'LOW' || key === 'BAIXA' || key === 'INFO') {
    return t.color.label;
  }
  return t.color.warn;
}