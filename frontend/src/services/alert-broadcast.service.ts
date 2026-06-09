/**
 * AlertBroadcastService
 *
 * Connects to the backend SSE stream (/swarm/stream) and translates every
 * swarm event into a typed AlertBroadcast that the AppComponent displays
 * as a Material-styled toast notification.
 *
 * Also exposes an Observable<SwarmEvent> so any component can react to
 * specific event topics (e.g., surveillance dashboard auto-refreshes on
 * alert.detected).
 */

import { Injectable, OnDestroy } from '@angular/core';
import { Subject, Observable } from 'rxjs';
import { filter } from 'rxjs/operators';

export interface SwarmEventPayload {
  topic: string;
  source: string;
  ts: string;
  payload: Record<string, any>;
}

export interface AlertBroadcast {
  id: number;
  topic: string;
  title: string;
  message: string;
  type: 'critical' | 'warning' | 'info' | 'success';
  icon: string;
  county?: string;
  syndrome?: string;
  ts: string;
  payload: Record<string, any>;
}

// Topics that should NOT be shown as toasts (too noisy)
const SILENT_TOPICS = new Set([
  'connected',
  'encounter.stored', // shown via session updates instead
  'task.followup_reminders.complete',
  'task.offline_queue_sync.complete',
  'task.baseline_update.complete',
]);

@Injectable({ providedIn: 'root' })
export class AlertBroadcastService implements OnDestroy {
  private _events$ = new Subject<SwarmEventPayload>();
  private _alerts$ = new Subject<AlertBroadcast>();
  private _counter = 0;
  private _es: EventSource | null = null;
  private _reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private _connected = false;
  // Exponential backoff state
  private _failureCount = 0;
  private readonly _BASE_DELAY_MS = 5_000;
  private readonly _MAX_DELAY_MS = 60_000;
  private readonly _MAX_FAILURES = 5; // stop auto-retrying after 5 consecutive failures

  /** Stream of ALL parsed swarm events — use filter(e => e.topic === '...') */
  readonly events$: Observable<SwarmEventPayload> =
    this._events$.asObservable();

  /** Stream of only the events that should show a toast */
  readonly alerts$: Observable<AlertBroadcast> = this._alerts$.asObservable();

  /** Whether the SSE connection is currently open */
  get connected(): boolean {
    return this._connected;
  }

  constructor() {
    this._connect();
  }

  private _connect(): void {
    // Don't retry if browser is offline or we've exceeded the failure cap
    if (!navigator.onLine) {
      const onOnline = () => {
        window.removeEventListener('online', onOnline);
        this._failureCount = 0;
        this._connect();
      };
      window.addEventListener('online', onOnline);
      return;
    }

    if (this._failureCount >= this._MAX_FAILURES) {
      // Give up until the user navigates or the page reloads.
      // A manual reconnect is possible by calling _resetAndConnect().
      console.warn(
        `[AlertBroadcast] SSE gave up after ${this._MAX_FAILURES} failures — ` +
          'will retry when browser comes back online.',
      );
      const onOnline = () => {
        window.removeEventListener('online', onOnline);
        this._failureCount = 0;
        this._connect();
      };
      window.addEventListener('online', onOnline);
      return;
    }

    try {
      this._es = new EventSource('/swarm/stream');

      this._es.onopen = () => {
        this._connected = true;
        this._failureCount = 0; // reset backoff on successful connection
        console.info('[AlertBroadcast] SSE connected to /swarm/stream');
      };

      this._es.onmessage = (e: MessageEvent) => {
        try {
          const event: SwarmEventPayload = JSON.parse(e.data);
          this._events$.next(event);
          if (!SILENT_TOPICS.has(event.topic)) {
            const broadcast = this._toBroadcast(event);
            if (broadcast) this._alerts$.next(broadcast);
          }
        } catch {
          // ignore malformed events
        }
      };

      this._es.onerror = () => {
        this._connected = false;
        this._es?.close();
        this._es = null;

        this._failureCount++;
        // Exponential backoff: 5s, 10s, 20s, 40s, 60s (capped)
        const delay = Math.min(
          this._BASE_DELAY_MS * Math.pow(2, this._failureCount - 1),
          this._MAX_DELAY_MS,
        );
        console.debug(
          `[AlertBroadcast] SSE error (attempt ${this._failureCount}/${this._MAX_FAILURES}) — retrying in ${delay / 1000}s`,
        );
        this._reconnectTimer = setTimeout(() => this._connect(), delay);
      };
    } catch {
      // SSE not supported or backend not running — fail silently
    }
  }

  /** Filter events$ by topic prefix for component-level subscriptions */
  on(topicPrefix: string): Observable<SwarmEventPayload> {
    return this.events$.pipe(filter((e) => e.topic.startsWith(topicPrefix)));
  }

  /**
   * Manually reset backoff state and reconnect.
   * Call this from a UI "Reconnect" button when the user is back online.
   */
  reconnect(): void {
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    this._es?.close();
    this._es = null;
    this._failureCount = 0;
    this._connect();
  }

  ngOnDestroy(): void {
    this._es?.close();
    if (this._reconnectTimer) clearTimeout(this._reconnectTimer);
    this._events$.complete();
    this._alerts$.complete();
  }

  // ── Event → Broadcast mapping ───────────────────────────────────────────────

  private _toBroadcast(event: SwarmEventPayload): AlertBroadcast | null {
    const { topic, source, ts, payload } = event;
    const county = payload['county'] ?? payload['location']?.county ?? '';
    const syndrome = payload['syndrome'] ?? '';
    const id = ++this._counter;
    const base = { id, topic, ts, county, syndrome, payload };

    // ── Outbreak alerts ────────────────────────────────────────────────────
    if (topic === 'alert.detected') {
      return {
        ...base,
        title: `🚨 Outbreak Alert: ${this._fmt(syndrome)}`,
        message: `${county} — ${payload['count'] ?? '?'} cases detected. Risk: ${payload['risk_level'] ?? 'ACTIVE'}`,
        type:
          payload['risk_level'] === 'HIGH' || payload['alert_level'] === 'RED'
            ? 'critical'
            : 'warning',
        icon: '🚨',
      };
    }

    // ── Silent pandemic ────────────────────────────────────────────────────
    if (topic === 'alert.silent_pandemic') {
      return {
        ...base,
        title: `🌊 Silent Pandemic: ${this._fmt(syndrome)}`,
        message: `${county} — persistent upward trend. Risk: ${payload['risk_level'] ?? '?'}`,
        type: payload['risk_level'] === 'HIGH' ? 'critical' : 'warning',
        icon: '🌊',
      };
    }

    // ── Cross-county spread ────────────────────────────────────────────────
    if (topic === 'alert.cross_county_spread') {
      return {
        ...base,
        title: `🔴 Cross-County Spread: ${this._fmt(syndrome)}`,
        message: `${payload['counties_count'] ?? '?'} counties affected — ${payload['escalation_level'] ?? 'REGIONAL'} escalation`,
        type: 'critical',
        icon: '🔴',
      };
    }

    // ── National escalation (from reflection) ──────────────────────────────
    if (topic === 'surveillance.escalation_needed') {
      const syndromes = Object.keys(
        payload['cross_county_syndromes'] ?? {},
      ).join(', ');
      return {
        ...base,
        title: '🔴 NATIONAL ESCALATION',
        message: `Cross-county spread: ${syndromes || 'multiple syndromes'}`,
        type: 'critical',
        icon: '🔴',
      };
    }

    // ── Contact tracing ────────────────────────────────────────────────────
    if (topic === 'contact_trace.contacts_identified') {
      return {
        ...base,
        title: `🔗 Contact Trace: ${payload['contacts_identified'] ?? 0} contacts`,
        message: `Trace ${payload['trace_id'] ?? ''} initiated for ${this._fmt(syndrome)}`,
        type: 'warning',
        icon: '🔗',
      };
    }

    if (topic === 'contact_trace.contact_confirmed') {
      return {
        ...base,
        title: '⚠️ Contact Confirmed as Case',
        message: `Secondary trace initiated from trace ${payload['trace_id'] ?? ''}`,
        type: 'critical',
        icon: '⚠️',
      };
    }

    // ── CHW outreach gap ───────────────────────────────────────────────────
    if (topic === 'gap.chw_outreach') {
      return {
        ...base,
        title: `👥 CHW Gap: ${county}`,
        message: `${payload['total_gap_wards'] ?? '?'} wards with zero submissions`,
        type: 'warning',
        icon: '👥',
      };
    }

    // ── Swarm task errors ──────────────────────────────────────────────────
    if (topic.endsWith('.error')) {
      return {
        ...base,
        title: '⚙️ Swarm Task Error',
        message: `Task ${topic.replace('.error', '')} failed: ${payload['error'] ?? 'unknown'}`,
        type: 'warning',
        icon: '⚙️',
      };
    }

    // ── Follow-up overdue ──────────────────────────────────────────────────
    if (topic === 'followup.overdue') {
      return {
        ...base,
        title: '📅 Follow-up Overdue',
        message: `${county} ${syndrome ? '— ' + this._fmt(syndrome) : ''} follow-up past due`,
        type: 'info',
        icon: '📅',
      };
    }

    // ── Protocol formulated ────────────────────────────────────────────────
    if (topic === 'task.outbreak_detection.complete') {
      return null; // too noisy — skip
    }

    return null; // all other topics are silent
  }

  private _fmt(s: string): string {
    return (s || 'unknown').replace(/_/g, ' ');
  }
}
