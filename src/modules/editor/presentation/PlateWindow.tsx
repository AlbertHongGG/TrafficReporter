import React from 'react';
import { listen } from '@tauri-apps/api/event';
import { getCurrentWindow } from '@tauri-apps/api/window';
import {
  AlertCircle,
  Check,
  FileOutput,
  LoaderCircle,
  RefreshCw,
  Search,
  Target,
  X,
} from 'lucide-react';
import {
  samplePrimaryText,
  PLATE_SESSION_UPDATED_EVENT,
  type PlateWindowSessionSnapshot,
} from '../application/plateWindow';
import { requestPlateWindowSession, sendPlateWindowAction } from '../infrastructure/plateWindowApi';
import { buildDefaultLprState, clamp, formatTransportTime } from '../domain/model';
import type { TimelineIntervalSelection } from '../../../shared/contracts';
import { createLogger, getErrorSummary, serializeError } from '../../../utils/logger';
import styles from './PlateWindow.module.css';

const log = createLogger('PlateWindow');

function formatConfidence(confidence: number) {
  return `${Math.round(clamp(confidence, 0, 1) * 100)}%`;
}

function formatIntervalLabel(interval: TimelineIntervalSelection | null) {
  if (!interval) {
    return '--';
  }

  return `${formatTransportTime(interval.startMs)} - ${formatTransportTime(interval.endMs)}`;
}

export const PlateWindow: React.FC = () => {
  const [snapshot, setSnapshot] = React.useState<PlateWindowSessionSnapshot | null>(null);
  const [countryHintsDraft, setCountryHintsDraft] = React.useState('');
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null);

  const lprState = snapshot?.lpr ?? buildDefaultLprState();
  const runtimeStatus = snapshot?.runtimeStatus ?? null;
  const topCandidate = snapshot?.topCandidate ?? lprState.candidates[0] ?? null;
  const isBusy = lprState.job.status === 'queued' || lprState.job.status === 'running';

  React.useEffect(() => {
    let disposed = false;
    let removeSessionListener: (() => void) | undefined;

    void listen<PlateWindowSessionSnapshot>(PLATE_SESSION_UPDATED_EVENT, (event) => {
      if (disposed) {
        return;
      }

      setSnapshot(event.payload);
      setErrorMessage(null);
    }).then((unlisten) => {
      removeSessionListener = unlisten;
    });

    void requestPlateWindowSession().catch((error) => {
      if (disposed) {
        return;
      }

      log.error('Failed to request the latest plate window session.', serializeError(error));
      setErrorMessage(getErrorSummary(error, 'Unable to connect to the main editor window.'));
    });

    return () => {
      disposed = true;
      removeSessionListener?.();
    };
  }, []);

  React.useEffect(() => {
    setCountryHintsDraft((snapshot?.lpr.countryHints ?? []).join(', '));
  }, [snapshot?.activeFileName, snapshot?.lpr.countryHints]);

  const sendAction = React.useCallback(async (action: Parameters<typeof sendPlateWindowAction>[0]) => {
    try {
      await sendPlateWindowAction(action);
      setErrorMessage(null);
    } catch (error) {
      log.error('Failed to send a plate window action.', {
        action,
        error: serializeError(error),
      });
      setErrorMessage(getErrorSummary(error, 'Unable to send the plate action.'));
    }
  }, []);

  const closeWindow = React.useCallback(async () => {
    await getCurrentWindow().close();
  }, []);

  return (
    <div className={styles.window}>
      <div data-tauri-drag-region className={styles.chrome}>
        <div className={styles.chromeMeta} data-tauri-drag-region>
          <span className={styles.chromeTitle}>{snapshot?.activeFileName ?? 'Plate'}</span>
          <span className={`${styles.runtimeBadge} ${runtimeStatus?.available ? styles.runtimeBadgeReady : styles.runtimeBadgeOffline}`}>
            {runtimeStatus?.available ? 'local' : 'offline'}
          </span>
        </div>
        <div className={styles.chromeActions}>
          <button type="button" className={styles.chromeButton} onClick={() => void sendAction({ type: 'refresh-runtime' })} aria-label="Refresh plate runtime">
            <RefreshCw size={14} />
          </button>
          <button type="button" className={`${styles.chromeButton} ${styles.chromeButtonClose}`} onClick={() => void closeWindow()} aria-label="Close plate window">
            <X size={14} />
          </button>
        </div>
      </div>

      <div className={styles.body}>
        {!snapshot?.hasActiveFile && (
          <div className={styles.emptyState}>Import a file to start plate analysis.</div>
        )}

        {snapshot?.hasActiveFile && (
          <>
            <section className={styles.block}>
              <div className={styles.intervalRow}>
                <button type="button" className={styles.secondaryButton} onClick={() => void sendAction({ type: 'use-clip-interval' })}>
                  Clip
                </button>
                <button type="button" className={styles.secondaryButton} onClick={() => void sendAction({ type: 'set-interval-boundary', boundary: 'start' })}>
                  In
                </button>
                <button type="button" className={styles.secondaryButton} onClick={() => void sendAction({ type: 'set-interval-boundary', boundary: 'end' })}>
                  Out
                </button>
                <button type="button" className={styles.secondaryButton} onClick={() => void sendAction({ type: 'clear-interval' })} disabled={!snapshot.explicitInterval}>
                  Clear
                </button>
              </div>
              <div className={styles.intervalValue}>{formatIntervalLabel(snapshot.effectiveInterval)}</div>
            </section>

            <section className={styles.block}>
              <input
                type="text"
                className={styles.input}
                value={countryHintsDraft}
                onChange={(event) => setCountryHintsDraft(event.target.value)}
                onBlur={() => void sendAction({ type: 'set-country-hints', value: countryHintsDraft })}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    void sendAction({ type: 'set-country-hints', value: countryHintsDraft });
                    event.currentTarget.blur();
                  }
                }}
                placeholder="country hints"
              />
            </section>

            <section className={styles.block}>
              <div className={styles.actionGrid}>
                <button type="button" className={styles.primaryButton} onClick={() => void sendAction({ type: 'scan-targets' })} disabled={isBusy}>
                  <Target size={14} />
                  Targets
                </button>
                <button type="button" className={styles.secondaryButton} onClick={() => void sendAction({ type: 'analyze-frame' })} disabled={isBusy}>
                  <Search size={14} />
                  Frame
                </button>
                <button type="button" className={styles.secondaryButton} onClick={() => void sendAction({ type: 'analyze-range' })} disabled={!snapshot.canAnalyzeRange || isBusy}>
                  <Target size={14} />
                  Range
                </button>
                <button
                  type="button"
                  className={`${styles.toggleButton} ${lprState.useDenseSampling ? styles.toggleButtonActive : ''}`}
                  onClick={() => void sendAction({ type: 'toggle-dense-sampling' })}
                >
                  More Samples
                </button>
                <button type="button" className={styles.secondaryButton} onClick={() => void sendAction({ type: 'export-evidence' })} disabled={!topCandidate && lprState.samples.length === 0}>
                  <FileOutput size={14} />
                  Evidence
                </button>
                <button type="button" className={styles.secondaryButton} onClick={() => void sendAction({ type: 'clear-results' })} disabled={lprState.candidates.length === 0 && lprState.targetTracks.length === 0}>
                  <X size={14} />
                  Reset
                </button>
              </div>
            </section>

            <section className={styles.block}>
              <div className={styles.statusRow}>
                {isBusy ? <LoaderCircle size={14} className={styles.spinningIcon} /> : topCandidate ? <Check size={14} /> : <AlertCircle size={14} />}
                <span>{lprState.job.detail || runtimeStatus?.detail || 'Local analysis ready.'}</span>
              </div>
              {(lprState.job.error || errorMessage) && <div className={styles.errorText}>{lprState.job.error ?? errorMessage}</div>}
            </section>

            <section className={styles.resultStrip}>
              <div className={styles.resultPrimary}>{topCandidate?.text ?? '--'}</div>
              <div className={styles.resultConfidence}>{topCandidate ? formatConfidence(topCandidate.confidence) : '0%'}</div>
            </section>

            <section className={styles.listBlock}>
              <div className={styles.listHeader}>Candidates</div>
              <div className={styles.listBody}>
                {lprState.candidates.length === 0 && <div className={styles.emptyInline}>No candidates.</div>}
                {lprState.candidates.map((candidate) => (
                  <button
                    key={candidate.id}
                    type="button"
                    className={`${styles.listButton} ${candidate.id === lprState.acceptedCandidateId ? styles.listButtonActive : ''}`}
                    onClick={() => void sendAction({ type: 'accept-candidate', candidateId: candidate.id })}
                  >
                    <span>{candidate.text}</span>
                    <span>{formatConfidence(candidate.confidence)}</span>
                  </button>
                ))}
              </div>
            </section>

            <div className={styles.splitColumns}>
              <section className={styles.listBlock}>
                <div className={styles.listHeader}>Targets</div>
                <div className={styles.listBody}>
                  {lprState.targetTracks.length === 0 && <div className={styles.emptyInline}>No targets.</div>}
                  {lprState.targetTracks.map((track) => (
                    <button
                      key={track.id}
                      type="button"
                      className={`${styles.listButton} ${track.id === lprState.selectedTargetTrackId ? styles.listButtonActive : ''}`}
                      onClick={() => void sendAction({ type: 'select-target-track', targetTrackId: track.id })}
                    >
                      <span>{track.label}</span>
                      <span>{formatConfidence(track.confidence)}</span>
                    </button>
                  ))}
                </div>
              </section>

              <section className={`${styles.listBlock} ${styles.samplesBlock}`}>
                <div className={styles.listHeader}>Samples</div>
                <div className={`${styles.listBody} ${styles.samplesListBody}`}>
                  {lprState.samples.length === 0 && <div className={styles.emptyInline}>No samples.</div>}
                  {lprState.samples.map((sample) => (
                    <div key={sample.id} className={styles.sampleRow}>
                      <div className={styles.sampleMain}>
                        <span>{formatTransportTime(sample.timeMs)}</span>
                        <span>{samplePrimaryText(sample)}</span>
                      </div>
                      <span className={styles.sampleBadge}>Quality {formatConfidence(sample.quality?.overallScore ?? 0)}</span>
                    </div>
                  ))}
                </div>
              </section>
            </div>

            <section className={styles.listBlock}>
              <div className={styles.listHeader}>History</div>
              <div className={styles.listBody}>
                {lprState.history.length === 0 && <div className={styles.emptyInline}>No history.</div>}
                {lprState.history.slice().reverse().map((entry) => (
                  <div key={entry.id} className={styles.historyRow}>
                    <span>{entry.summary}</span>
                    <span>{entry.interval ? formatIntervalLabel(entry.interval) : 'frame'}</span>
                  </div>
                ))}
              </div>
            </section>
          </>
        )}
      </div>
    </div>
  );
};
