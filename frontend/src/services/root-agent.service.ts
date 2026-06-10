/**
 * Root Agent Service — SihaLink
 *
 * Central coordinator that orchestrates all sub-agents through the Orchestrator backend.
 * This service acts as the main entry point for frontend-to-backend communication,
 * ensuring all agents are accessible through a unified interface.
 *
 * Pattern: Delegates to specialized agent services which communicate with the backend.
 */

import { Injectable } from '@angular/core';
import { BehaviorSubject, Observable } from 'rxjs';
import { IntakeAgentService } from './agents/intake-agent.service';
import { GeoAgentService } from './agents/geo-agent.service';
import { DataAgentService } from './agents/data-agent.service';
import { NotifyAgentService } from './agents/notify-agent.service';
import { SurveillanceAgentService } from './agents/surveillance-agent.service';
import { ContactTracingAgentService } from './agents/contact-tracing-agent.service';
import { ApiService } from './api.service';

/**
 * Represents the state of a complete encounter workflow.
 * States mirror EncounterState enum in agents/orchestrator/state_machine.py.
 */
export interface EncounterSession {
  sessionId: string;
  state:
    | 'IDLE'
    | 'LISTENING'
    | 'EXTRACTING'
    | 'CLARIFICATION_GATE'
    | 'GEOCODING'
    | 'STORING'
    | 'FOLLOW_UP_SCHEDULED'
    | 'ALERTING'
    | 'DECISION_GATE'
    | 'NOTIFYING'
    | 'COMPLETE'
    | 'OFFLINE_QUEUED'
    | 'SYNCING'
    | 'FAILED';
  data: {
    audio?: string;
    extraction?: any;
    location?: { latitude: number; longitude: number };
    geoEnriched?: any;
    mongoStored?: any;
    notifications?: any[];
    surveillanceData?: any;
    gate_data?: { question?: string; triage_color?: string; summary?: string };
  };
  timestamp: number;
  error?: string;
}

@Injectable({
  providedIn: 'root',
})
export class RootAgentService {
  private activeSessions = new Map<string, EncounterSession>();
  private sessionUpdates = new BehaviorSubject<EncounterSession | null>(null);
  public sessionUpdates$ = this.sessionUpdates.asObservable();

  private agentStatus = new BehaviorSubject<{
    intake: boolean;
    geo: boolean;
    data: boolean;
    notify: boolean;
    surveillance: boolean;
    contact_tracing: boolean;
  }>({
    intake: false,
    geo: false,
    data: false,
    notify: false,
    surveillance: false,
    contact_tracing: false,
  });
  public agentStatus$ = this.agentStatus.asObservable();

  constructor(
    private intakeAgent: IntakeAgentService,
    private geoAgent: GeoAgentService,
    private dataAgent: DataAgentService,
    private notifyAgent: NotifyAgentService,
    private surveillanceAgent: SurveillanceAgentService,
    private contactTracingAgent: ContactTracingAgentService,
    private api: ApiService,
  ) {
    this.checkAgentHealth();
  }

  /**
   * Start a complete encounter workflow through the orchestrator backend.
   *
   * Per APP_WORKFLOW.md: the full pipeline (EXTRACTING → GEOCODING → STORING →
   * FOLLOW_UP_SCHEDULED → ALERTING → DECISION_GATE → NOTIFYING → COMPLETE)
   * runs server-side as a background task.  This method:
   *   1. POSTs to /encounter/start to kick off the server-side lifecycle
   *   2. Polls /encounter/{id}/status every 2 seconds
   *   3. Updates the local session object on each poll so the dashboard
   *      reflects real state transitions including CLARIFICATION_GATE and
   *      DECISION_GATE
   *   4. Resolves when the session reaches COMPLETE, FAILED, or times out (5 min)
   */
  async startEncounter(params: {
    audio_base64: string;
    latitude?: number;
    longitude?: number;
    chw_id?: string;
    sessionId?: string;
    form_data?: any;
    telegram_payload?: any;
  }): Promise<EncounterSession> {
    const sessionId = params.sessionId || `encounter-${Date.now()}`;

    const session: EncounterSession = {
      sessionId,
      state: 'LISTENING',
      data: {
        audio: params.audio_base64,
        location:
          params.latitude && params.longitude
            ? { latitude: params.latitude, longitude: params.longitude }
            : undefined,
      },
      timestamp: Date.now(),
    };

    this.activeSessions.set(sessionId, session);
    this.sessionUpdates.next(session);

    // ── POST to backend — starts the real state-machine lifecycle ────────────
    try {
      await this.api.post('/encounter/start', {
        session_id: sessionId,
        audio_base64: params.audio_base64 || '',
        latitude: params.latitude ?? 0,
        longitude: params.longitude ?? 0,
        chw_id: params.chw_id,
        form_data: params.form_data,
        telegram_payload: params.telegram_payload,
      });
    } catch (err) {
      // Backend unavailable — queue offline
      session.state = 'OFFLINE_QUEUED';
      session.error =
        err instanceof Error ? err.message : 'Backend unreachable';
      this.sessionUpdates.next(session);
      return session;
    }

    // ── Poll backend state every 2 seconds until terminal state ─────────────
    const TERMINAL = new Set(['COMPLETE', 'FAILED', 'OFFLINE_QUEUED']);
    const POLL_INTERVAL_MS = 2000;
    const TIMEOUT_MS = 5 * 60 * 1000; // 5 minutes
    const deadline = Date.now() + TIMEOUT_MS;

    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));

      try {
        const status: any = await this.api.get(
          `/encounter/${encodeURIComponent(sessionId)}/status`,
        );
        // Merge backend state into the local session
        session.state = status.state ?? session.state;
        const d = status.data ?? {};
        if (d.extracted) session.data.extraction = d.extracted;
        if (d.enriched) session.data.geoEnriched = d.enriched;
        if (d.encounter_id) session.data.mongoStored = { id: d.encounter_id };
        if (d.gate_data) session.data.gate_data = d.gate_data;
        if (status.error) session.error = status.error;

        this.activeSessions.set(sessionId, session);
        this.sessionUpdates.next({ ...session });

        if (TERMINAL.has(session.state)) break;
      } catch {
        // Transient poll failure — keep trying
      }
    }

    return session;
  }

  /**
   * Get status of a specific encounter session
   */
  async getEncounterStatus(
    sessionId: string,
  ): Promise<EncounterSession | null> {
    return this.activeSessions.get(sessionId) || null;
  }

  /**
   * Confirm or decline a human-in-the-loop decision gate.
   * Calls POST /encounter/{sessionId}/confirm on the backend.
   * The backend's asyncio.Future resolves and the pipeline continues.
   */
  async confirmEncounterDecision(
    sessionId: string,
    confirmed: boolean,
  ): Promise<void> {
    const session = this.activeSessions.get(sessionId);
    if (!session) throw new Error(`Session ${sessionId} not found`);

    await this.api.post(`/encounter/${encodeURIComponent(sessionId)}/confirm`, {
      confirmed,
    });

    if (!confirmed) {
      session.state = 'COMPLETE';
      this.sessionUpdates.next(session);
    }
  }

  /**
   * Submit a clarification answer for an encounter in CLARIFICATION_GATE state.
   * Calls POST /encounter/{sessionId}/clarify on the backend.
   */
  async submitClarificationAnswer(
    sessionId: string,
    answer: string,
  ): Promise<void> {
    await this.api.post(`/encounter/${encodeURIComponent(sessionId)}/clarify`, {
      answer,
    });
  }

  /**
   * Access Intake Agent directly for specialized operations
   */
  getIntakeAgent(): IntakeAgentService {
    return this.intakeAgent;
  }

  /**
   * Access Geo Agent directly for specialized operations
   */
  getGeoAgent(): GeoAgentService {
    return this.geoAgent;
  }

  /**
   * Access Data Agent directly for specialized operations
   */
  getDataAgent(): DataAgentService {
    return this.dataAgent;
  }

  /**
   * Access Notify Agent directly for specialized operations
   */
  getNotifyAgent(): NotifyAgentService {
    return this.notifyAgent;
  }

  /**
   * Access Surveillance Agent directly for specialized operations
   */
  getSurveillanceAgent(): SurveillanceAgentService {
    return this.surveillanceAgent;
  }

  /**
   * Check health status of all agents.
   * Runs silently — failures are expected when the backend is not yet running.
   */
  async checkAgentHealth(): Promise<void> {
    const check = (p: Promise<any>) => p.then(() => true).catch(() => false);
    try {
      const [intake, geo, data, notify, surveillance, contact_tracing] =
        await Promise.all([
          check(this.intakeAgent.healthCheck()),
          check(this.geoAgent.healthCheck()),
          check(this.dataAgent.healthCheck()),
          check(this.notifyAgent.healthCheck()),
          check(this.surveillanceAgent.healthCheck()),
          check(this.contactTracingAgent.healthCheck()),
        ]);
      this.agentStatus.next({
        intake,
        geo,
        data,
        notify,
        surveillance,
        contact_tracing,
      });
    } catch {
      // Backend not running — stay in default all-false state
    }
  }

  /**
   * Get all active sessions
   */
  getActiveSessions(): EncounterSession[] {
    return Array.from(this.activeSessions.values());
  }

  /**
   * Clear session from memory
   */
  clearSession(sessionId: string): void {
    this.activeSessions.delete(sessionId);
  }
}
