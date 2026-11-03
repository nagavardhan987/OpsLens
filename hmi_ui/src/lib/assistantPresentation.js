export function assistantDisplayStatus(answer) {
  if (answer?.fallback_used === true || answer?.llm_used !== true) {
    return { text: 'Evidence-based answer', tone: 'evidence' };
  }
  return { text: 'AI-generated answer', tone: 'ai' };
}

export function assistantFallbackExplanation(answer) {
  const reason = String(answer?.fallback_reason || answer?.provider_metadata?.correction_failure_reason || '').toLowerCase();
  const provider = String(answer?.selected_provider || answer?.provider_metadata?.selected_provider || '').toLowerCase();
  if (reason === 'deterministic_record_grounded' && (!provider || ['none', 'off', 'disabled'].includes(provider))) {
    return 'No language model is enabled; OpsLens answered from the selected incident’s verified records.';
  }
  if (['timeout', 'connection_error', 'connect_timeout', 'read_timeout', 'unavailable', 'busy', 'rate_limit', 'auth', 'configuration', 'empty'].includes(reason)) {
    const names = { timeout: 'timed out', connection_error: 'could not be reached', connect_timeout: 'could not be reached', read_timeout: 'timed out', unavailable: 'was unavailable', busy: 'was busy', rate_limit: 'was rate limited', auth: 'rejected authentication', configuration: 'is not configured correctly', empty: 'returned an empty response' };
    return `The AI provider ${names[reason]}. OpsLens used evidence-based guidance from the incident record.`;
  }
  if (['ungrounded_numeric_value', 'ungrounded_timestamp', 'unretrieved_sop_instruction_claim', 'malformed_or_ungrounded_llm_output', 'malformed_response'].includes(reason)) {
    return 'The AI response did not pass grounding checks against the selected incident and retrieved procedure records, so it was not shown. OpsLens used evidence-based guidance instead.';
  }
  if (reason) return 'The AI response could not be completed or validated for this incident. OpsLens used evidence-based guidance instead.';
  return 'The AI response was not available for this request. OpsLens used evidence-based guidance instead.';
}

export function getVerifiedSopReferences(answer) {
  const bottomLine = String(answer?.operator_response?.bottom_line || answer?.answer || '').toLowerCase();
  // Never show verified SOP references when the bottom line or uncertainty status reports that SOP is unavailable or not retrieved
  if (answer?.uncertainty_status === 'insufficient_approved_procedure' && !answer?.has_approved_sop) return [];
  if (answer?.uncertainty_status === 'not_retrieved' || answer?.uncertainty_status === 'document_content_unavailable') return [];

  const isSopUnavailable = /\b(?:no|not|unavailable|not available|not retrieved|could not be found|not in the current records)\b.{0,60}\b(?:relevant\s+)?(?:sop|procedure|section)\b|\b(?:sop|procedure|section)\b.{0,60}\b(?:unavailable|not available|not retrieved|could not be found|unverified|not in the current records)\b/i.test(bottomLine);
  if (isSopUnavailable) return [];

  return (Array.isArray(answer?.sources) ? answer.sources : []).filter((source) =>
    source?.verified === true &&
    source?.approved === true &&
    typeof source?.sop_id === 'string' && source.sop_id.trim() &&
    typeof source?.section === 'string' && source.section.trim() &&
    typeof source?.text === 'string' && source.text.trim().length >= 20
  );
}

export function getUnverifiedSopReferences(answer) {
  // Keep a retrieved but unapproved excerpt visible with an explicit warning,
  // even when the bottom line correctly says no approved procedure was found.
  return (Array.isArray(answer?.sources) ? answer.sources : []).filter((source) =>
    source?.verified === true &&
    source?.approved !== true &&
    typeof source?.sop_id === 'string' && source.sop_id.trim() &&
    typeof source?.text === 'string' && source.text.trim().length >= 20
  );
}

export function sopDisplayStatus(resolution = {}) {
  if (resolution.status === 'retrieval_unavailable') return 'Unavailable';
  if (resolution.status === 'reference_unapproved') return 'Approval unverified';
  if (resolution.status === 'reference_approved') return 'Approved';
  return 'No approved procedure found';
}

export function formatTimestamp(value, locale) {
  if (typeof value !== 'string' || !value.trim()) return 'Time unavailable';
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime())) return 'Time unavailable';
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit', second: '2-digit', timeZoneName: 'short',
  }).format(parsed);
}

export function formatMeasurement(value, unit = '') {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  const number = Number.isInteger(value) ? String(value) : value.toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
  return `${number}${unit ? ` ${unit}` : ''}`;
}

export function formatAbsoluteChange(value, unit = '') {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'Change unavailable';
  const displayUnit = unit === '%' ? 'percentage points' : unit;
  const formatted = formatMeasurement(Math.abs(value), displayUnit);
  const direction = value > 0 ? 'increased by' : value < 0 ? 'decreased by' : 'was unchanged';
  return value === 0 ? direction : `${direction} ${formatted}`;
}

export function formatRelativeChange(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}% relative change`;
}
