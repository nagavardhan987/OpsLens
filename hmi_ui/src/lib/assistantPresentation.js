export function assistantDisplayStatus(answer) {
  const isHypothetical = answer?.uncertainty_status === 'hypothetical_reasoning' ||
    (typeof answer?.answer === 'string' && answer.answer.toLowerCase().includes('hypothetical')) ||
    (typeof answer?.operator_response?.bottom_line === 'string' && answer.operator_response.bottom_line.toLowerCase().includes('hypothetical'));

  if (answer?.llm_used === true && answer?.fallback_used !== true) {
    // Only name the provider when it's been genuinely used
    const provider = answer?.used_provider || answer?.selected_provider;
    const providerLabel = provider && provider !== 'none' && provider !== 'deterministic' ? provider : 'LLM';
    if (isHypothetical) {
      return { text: `Hypothetical analysis · generated via ${providerLabel}`, tone: 'ai' };
    }
    return { text: `AI-enhanced · grounded via ${providerLabel}`, tone: 'ai' };
  }

  if (answer?.fallback_used === true) {
    if (isHypothetical) {
      return { text: 'Hypothetical analysis · unobserved in stored records (deterministic fallback)', tone: 'fallback' };
    }
    const reason = answer?.fallback_reason;
    const reasonLabel = (reason && reason !== 'deterministic_record_grounded') ? ` (${reason})` : '';
    return { text: `Deterministic fallback · verified from stored data${reasonLabel}`, tone: 'fallback' };
  }

  return { text: 'Evidence-based response · verified records', tone: 'evidence' };
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
