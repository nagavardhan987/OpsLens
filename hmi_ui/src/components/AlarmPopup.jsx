import React, { useEffect, useRef, useState } from 'react';
import { MessageSquareText, X } from 'lucide-react';
import { getAlarmPopupPriority } from '../lib/alarmPopupPresentation';

/**
 * Non-intrusive HMI alarm notification for NEWLY arriving alarms.
 * Suppresses itself when the operator has already seen the incident on the
 * main panel (tracked by dismissedEventId ref) to avoid duplicate banners
 * for an already-visible alarm.
 * Auto-dismisses after 20 s; operator can dismiss manually.
 */
export default function AlarmPopup({ event, isActive, onOpenCopilot, onDismiss }) {
  const [visible, setVisible] = useState(false);
  const [animateIn, setAnimateIn] = useState(false);
  const dismissedId = useRef(null);
  const isFirstMount = useRef(true);
  const timerRef = useRef(null);

  useEffect(() => {
    // Clear any pending timer when event changes
    clearTimeout(timerRef.current);

    const eventId = event?.event_id;

    // Suppress popup on first page load if an incident is already loaded
    // and shown prominently on the main dashboard overview card.
    if (isFirstMount.current) {
      isFirstMount.current = false;
      if (eventId) {
        dismissedId.current = eventId;
      }
      return;
    }

    // Don't show if:
    // - No event / not active
    // - Same event that was already dismissed or already loaded on mount
    if (!event || !isActive || !eventId || eventId === dismissedId.current) {
      setAnimateIn(false);
      setTimeout(() => setVisible(false), 280);
      return;
    }

    // A genuinely new event — show the popup
    setVisible(true);
    const showTimer = setTimeout(() => setAnimateIn(true), 10);

    // Auto-dismiss after 20 s
    timerRef.current = setTimeout(() => {
      dismissedId.current = eventId;
      setAnimateIn(false);
      setTimeout(() => setVisible(false), 280);
    }, 20000);

    return () => {
      clearTimeout(showTimer);
      clearTimeout(timerRef.current);
    };
  }, [event?.event_id, isActive]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleDismiss = () => {
    dismissedId.current = event?.event_id;
    clearTimeout(timerRef.current);
    setAnimateIn(false);
    setTimeout(() => {
      setVisible(false);
      onDismiss?.();
    }, 280);
  };

  const handleOpenCopilot = () => {
    handleDismiss();
    onOpenCopilot?.();
  };

  if (!visible) return null;

  const candidate = event?.candidate || {};
  const story = event?.story || {};
  const steps = story.steps || [];
  const alarmStep = [...steps].reverse().find(s => String(s.tag || '').startsWith('ALM-'));
  const alarmId = alarmStep?.tag || candidate.primary_tag || candidate.alarm_id || 'Alarm';
  const equipment = (event?.correlated || {}).equipment_id || 'Equipment';
  const alarmDescription = alarmStep?.description || candidate.alarm_description || '';
  const popupPriority = getAlarmPopupPriority(event || {});
  const severityClass = `alarm-popup--${popupPriority.tone}`;

  return (
    <div
      className={`alarm-popup ${severityClass} ${animateIn ? 'alarm-popup-visible' : 'alarm-popup-entering'}`}
      role="alert"
      aria-label={`New alarm: ${alarmId}`}
      aria-live="assertive"
    >
      {/* Header row */}
      <div className="alarm-popup-header">
        <div className="alarm-popup-heading">
          <span className="alarm-popup-indicator" aria-hidden="true" />
          <span className="alarm-popup-priority">
            New alarm · {popupPriority.label}
          </span>
        </div>
        <button
          onClick={handleDismiss}
          className="alarm-popup-close"
          aria-label="Dismiss alarm notification"
          title="Dismiss notification"
        >
          <X size={17} />
        </button>
      </div>

      {/* Alarm ID & equipment */}
      <div className="alarm-popup-identity">
        <div className="alarm-popup-id">{alarmId}</div>
        <div className="alarm-popup-equipment">{equipment}</div>
      </div>

      {alarmDescription && <div className="alarm-popup-summary">{alarmDescription}</div>}

      {/* Action buttons */}
      <div className="alarm-popup-actions">
        <button
          onClick={handleOpenCopilot}
          className="alarm-popup-ask"
        >
          <MessageSquareText size={15} />
          Ask OpsLens
        </button>
        <button
          onClick={handleDismiss}
          className="alarm-popup-dismiss"
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}
