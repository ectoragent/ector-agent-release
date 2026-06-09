/** Junta trilha persistida do turno com linhas do segmento em streaming (sem duplicar). */
export const mergeLiveToolTrail = (segmentTrail, turnTrail) => {
  if (!turnTrail.length) {
    return segmentTrail;
  }
  if (!segmentTrail.length) {
    return turnTrail;
  }
  const seen = new Set(segmentTrail);
  return [...segmentTrail, ...turnTrail.filter(line => !seen.has(line))];
};
export const liveToolTrailProps = (feed, segmentTrail, uiBusy) => ({
  activity: feed.activity,
  busy: uiBusy,
  outcome: feed.outcome,
  reasoning: feed.reasoning,
  reasoningActive: feed.reasoningActive,
  reasoningStreaming: feed.reasoningStreaming,
  subagents: feed.subagents,
  toolTokens: feed.toolTokens,
  tools: feed.tools,
  trail: mergeLiveToolTrail(segmentTrail, feed.turnTrail)
});