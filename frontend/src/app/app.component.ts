/**
 * Root App Component — SihaLink (Standalone, Angular 17+)
 * Central shell with routing, online/offline handling, agent health polling,
 * and live swarm alert broadcasting via SSE.
 */

import { Component, OnInit, OnDestroy } from '@angular/core';
import { RouterModule, Router } from '@angular/router';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Observable, Subscription } from 'rxjs';
import { RootAgentService } from '../services/root-agent.service';
import { ApiService } from '../services/api.service';
import { OfflineSyncService } from '../services/offline-sync.service';
import {
  AlertBroadcastService,
  AlertBroadcast,
} from '../services/alert-broadcast.service';

export interface AppToast {
  id: number;
  message: string;
  title?: string;
  type: 'info' | 'success' | 'warning' | 'error' | 'critical';
  icon: string;
  county?: string;
  syndrome?: string;
}

@Component({
  selector: 'app-root',
  templateUrl: './app.component.html',
  styleUrl: './app.component.css',
  standalone: true,
  imports: [CommonModule, RouterModule, FormsModule],
})
export class AppComponent implements OnInit, OnDestroy {
  title = 'SihaLink - Multi-Agent System';
  isMenuOpen = false;

  agentStatus$!: Observable<any>;

  isOnline = navigator.onLine;
  offlineQueueSize = 0;
  gateSession: any = null;
  clarificationSession: any = null; // session waiting for CLARIFICATION_GATE answer
  clarificationAnswer = '';
  clarificationSubmitting = false;
  clarificationError: string | null = null;
  sseConnected = false;

  // Toast notification queue — holds both agent-health and live swarm alerts
  toasts: AppToast[] = [];
  private toastCounter = 0;
  private lastAgentStatus: any = null;
  private _subs: Subscription[] = [];

  private onlineHandler = () => {
    this.isOnline = true;
    this.broadcast.reconnect(); // reset SSE backoff now that we're online
    this.syncOfflineQueue();
  };
  private offlineHandler = () => {
    this.isOnline = false;
  };
  private healthInterval?: ReturnType<typeof setInterval>;

  constructor(
    private rootAgent: RootAgentService,
    private router: Router,
    private api: ApiService,
    private syncService: OfflineSyncService,
    private broadcast: AlertBroadcastService,
  ) {}

  ngOnInit() {
    this.agentStatus$ = this.rootAgent.agentStatus$;

    window.addEventListener('online', this.onlineHandler);
    window.addEventListener('offline', this.offlineHandler);
    this.offlineQueueSize = this.syncService.getQueueSize();

    this.rootAgent.checkAgentHealth();
    this.healthInterval = setInterval(
      () => this.rootAgent.checkAgentHealth(),
      30_000,
    );

    // ── Agent health change toasts ───────────────────────────────────────────
    this._subs.push(
      this.agentStatus$.subscribe((status) => {
        if (!status || !this.lastAgentStatus) {
          this.lastAgentStatus = status;
          return;
        }
        const labels: Record<string, string> = {
          intake: '🎤 Intake',
          geo: '📍 Geo',
          data: '💾 Data',
          notify: '📨 Notify',
          surveillance: '📊 Surveillance',
          contact_tracing: '🔗 Contact Tracing',
        };
        for (const agent of Object.keys(labels)) {
          const wasOk = this.lastAgentStatus[agent];
          const isOk = status[agent];
          if (!wasOk && isOk)
            this.showToast(
              `${labels[agent]} Agent is back online`,
              'success',
              '✅',
            );
          if (wasOk && !isOk)
            this.showToast(
              `${labels[agent]} Agent went offline`,
              'warning',
              '⚠️',
            );
        }
        this.lastAgentStatus = status;
      }),
    );

    // ── Decision gate toasts ─────────────────────────────────────────────────
    this._subs.push(
      this.rootAgent.sessionUpdates$.subscribe((session) => {
        if (!session) return;

        if (session?.state === 'DECISION_GATE') {
          this.gateSession = session;
          this.showToast(
            'Clinical gate requires your approval',
            'warning',
            '🔔',
          );
        } else if (session?.state === 'CLARIFICATION_GATE') {
          // New or updated clarification — only replace if it's a new question
          // to avoid flickering while the user is typing their answer
          if (
            !this.clarificationSession ||
            this.clarificationSession.sessionId !== session.sessionId
          ) {
            this.clarificationSession = session;
            this.clarificationAnswer = '';
            this.clarificationError = null;
            this.clarificationSubmitting = false;
          } else {
            // Same session — update gate_data in case question changed
            this.clarificationSession = session;
          }
          this.showToast(
            'CHV clarification needed — answer below',
            'info',
            '❓',
          );
        } else {
          // Clear gate modals when the session moves to a non-gate state
          if (this.gateSession?.sessionId === session.sessionId) {
            this.gateSession = null;
          }
          if (this.clarificationSession?.sessionId === session.sessionId) {
            this.clarificationSession = null;
            this.clarificationAnswer = '';
            this.clarificationError = null;
            this.clarificationSubmitting = false;
          }
        }
      }),
    );

    // ── Live swarm alerts from SSE ───────────────────────────────────────────
    this._subs.push(
      this.broadcast.alerts$.subscribe((alert: AlertBroadcast) => {
        this.showSwarmAlert(alert);
      }),
    );

    // Track SSE connection status
    this._subs.push(
      this.broadcast.on('connected').subscribe(() => {
        this.sseConnected = true;
      }),
    );

    if (this.isOnline && this.offlineQueueSize > 0) this.syncOfflineQueue();
  }

  // ── Toast helpers ──────────────────────────────────────────────────────────

  showToast(
    message: string,
    type: AppToast['type'] = 'info',
    icon = 'ℹ️',
    title?: string,
    county?: string,
    syndrome?: string,
  ) {
    const id = ++this.toastCounter;
    const ttl = type === 'critical' ? 8000 : type === 'warning' ? 6000 : 4000;
    this.toasts = [
      { id, message, title, type, icon, county, syndrome },
      ...this.toasts,
    ].slice(0, 8);
    setTimeout(() => this.dismissToast(id), ttl);
  }

  showSwarmAlert(alert: AlertBroadcast) {
    this.showToast(
      alert.message,
      alert.type === 'critical' ? 'critical' : (alert.type as AppToast['type']),
      alert.icon,
      alert.title,
      alert.county,
      alert.syndrome,
    );
  }

  dismissToast(id: number) {
    this.toasts = this.toasts.filter((t) => t.id !== id);
  }

  dismissAll() {
    this.toasts = [];
  }

  // ── Gate confirmation ──────────────────────────────────────────────────────

  /** Resolve triage color from gate session — checks gate_data then extraction fallback */
  resolveGateTriage(session: any): string {
    return (
      session?.data?.gate_data?.triage_color ||
      session?.data?.extraction?.triage_color ||
      session?.data?.extraction?.['triage_color'] ||
      'YELLOW'
    );
  }

  resolveGateSyndrome(session: any): string {
    return (
      session?.data?.gate_data?.syndrome ||
      session?.data?.extraction?.syndrome ||
      ''
    );
  }

  resolveGateComplaint(session: any): string {
    return (
      session?.data?.gate_data?.summary ||
      session?.data?.extraction?.chief_complaint ||
      session?.data?.extraction?.original_complaint ||
      ''
    );
  }

  resolveGateSymptoms(session: any): string[] {
    const s =
      session?.data?.gate_data?.symptoms ||
      session?.data?.extraction?.symptoms ||
      session?.data?.extraction?.primary_symptoms ||
      [];
    return Array.isArray(s) ? s : [];
  }

  async confirmGate(confirmed: boolean) {
    if (!this.gateSession) return;
    const sessionId = this.gateSession.sessionId;
    this.gateSession = null; // close immediately

    try {
      const { timedOut } = await this.rootAgent.confirmEncounterDecision(
        sessionId,
        confirmed,
      );
      if (timedOut) {
        this.showToast(
          'Gate timed out — encounter was auto-processed',
          'warning',
          '⏱️',
        );
      }
    } catch (error) {
      console.error('Failed to confirm decision gate:', error);
    }
  }

  async submitClarification() {
    if (!this.clarificationSession || !this.clarificationAnswer.trim()) return;
    this.clarificationSubmitting = true;
    this.clarificationError = null;
    try {
      await this.rootAgent.submitClarificationAnswer(
        this.clarificationSession.sessionId,
        this.clarificationAnswer.trim(),
      );
      // Optimistically close the modal — the poll will confirm when backend moves on
      this.clarificationAnswer = '';
      this.clarificationSession = null;
      this.clarificationSubmitting = false;
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      // 404 means the gate already timed out — close gracefully
      if (msg.includes('404') || msg.includes('No active clarification')) {
        this.clarificationSession = null;
        this.clarificationAnswer = '';
        this.clarificationSubmitting = false;
      } else {
        this.clarificationError = 'Could not submit answer. Try again.';
        this.clarificationSubmitting = false;
        console.error('Failed to submit clarification:', error);
      }
    }
  }

  /** Skip the clarification gate — sends a blank answer so the pipeline continues. */
  async skipClarification() {
    if (!this.clarificationSession) return;
    this.clarificationSubmitting = true;
    try {
      // Send a skip signal — backend treats empty/skip as "no clarification"
      await this.rootAgent.submitClarificationAnswer(
        this.clarificationSession.sessionId,
        '__skip__',
      );
    } catch {
      // Gate may have timed out — that's fine
    } finally {
      this.clarificationSession = null;
      this.clarificationAnswer = '';
      this.clarificationError = null;
      this.clarificationSubmitting = false;
    }
  }

  // ── Lifecycle ──────────────────────────────────────────────────────────────

  ngOnDestroy() {
    window.removeEventListener('online', this.onlineHandler);
    window.removeEventListener('offline', this.offlineHandler);
    if (this.healthInterval) clearInterval(this.healthInterval);
    this._subs.forEach((s) => s.unsubscribe());
  }

  toggleMenu() {
    this.isMenuOpen = !this.isMenuOpen;
  }
  navigateTo(path: string) {
    this.router.navigate([path]);
    this.isMenuOpen = false;
  }

  private async syncOfflineQueue() {
    try {
      const queue = this.syncService.getQueue();
      for (const encounter of queue) {
        try {
          await this.rootAgent.startEncounter(encounter);
          this.syncService.removeFromQueue(encounter);
        } catch {
          /* non-fatal */
        }
      }
      this.offlineQueueSize = this.syncService.getQueueSize();
    } catch {
      /* non-fatal */
    }
  }
}
