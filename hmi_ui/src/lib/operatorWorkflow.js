/** True only when a recorded source clear sample is strictly newer than the alarm trip. */
export function hasSubsequentClearAlarmReading(state) {
  return state?.observed === true &&
    state?.active === false &&
    state?.is_later_than_alarm === true &&
    typeof state?.timestamp === 'string' &&
    Number.isFinite(Date.parse(state.timestamp));
}

/** Map operator intent to an audit action or the dedicated status endpoint. */
export function getWorkflowSubmission(actionType, notes = '') {
  if (actionType === 'LOG_EVENT') {
    return { kind: 'audit', actionType: 'ANNOTATE', notes: String(notes).trim() };
  }
  if (actionType === 'MARK_UNRESOLVED') {
    return { kind: 'status', actionType: 'MARK_UNRESOLVED', reason: String(notes).trim() || null };
  }
  return { kind: 'audit', actionType, notes: notes || null };
}

/** Human-safe operator feedback; backend validation text is deliberately ignored. */
export function workflowActionFailureMessage(actionType, error) {
  if (actionType === 'RESOLVE' && error?.status === 400) {
    return 'Resolution is still locked. A later source-clear reading and operator confirmation are required.';
  }
  if (actionType === 'LOG_EVENT') return 'The event note was not saved. Check the note and try again.';
  if (actionType === 'MARK_UNRESOLVED') return 'The incident could not be marked unresolved. Try again.';
  if (actionType === 'VERIFY') return 'Verification could not be recorded. Try again.';
  if (actionType === 'INSPECT' || actionType === 'INSPECTED') return 'The inspection record could not be saved. Try again.';
  if (error?.status === 404) return 'This incident is no longer available. Refresh the alarm list and select it again.';
  return 'The operator action could not be saved. Check the connection and try again.';
}

export function workflowActionSuccessMessage(actionType) {
  if (actionType === 'LOG_EVENT') return 'Event note saved to the incident audit history.';
  if (actionType === 'MARK_UNRESOLVED') return 'Incident marked unresolved and returned to the active alarm list.';
  if (actionType === 'VERIFY' || actionType === 'VERIFIED') return 'Operator verification recorded. Alarm state is unchanged.';
  if (actionType === 'INSPECT' || actionType === 'INSPECTED') return 'Inspection acknowledgement recorded.';
  if (actionType === 'RESOLVE' || actionType === 'RESOLVED') return 'Operator resolution confirmation recorded.';
  return 'Operator action recorded.';
}
