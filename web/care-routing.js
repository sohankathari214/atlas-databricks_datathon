export function emergencySigns(text) {
  const problem = text.normalize('NFKC').toLowerCase();
  return /\b(?:chest (?:pain|pains|pressure|tightness|discomfort)|(?:pain|pressure|tightness|discomfort) (?:in|across) (?:my |the |their )?chest|(?:having|suspected|possible) (?:a )?(?:heart attack|stroke)|can't breathe|cannot breathe|can’t breathe|severe (?:shortness of breath|trouble breathing|bleeding)|uncontrollable bleeding|unresponsive|face drooping|facial droop)\b/.test(problem);
}
