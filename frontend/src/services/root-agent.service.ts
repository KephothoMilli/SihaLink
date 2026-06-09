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

/**
 * Represents the state of a complete encounter workflow
 */
export interface EncounterSession {
  sessionId: string;
  state:
    | 'IDLE'
    | 'LISTENING'
    | 'EXTRACTING'
    | 'GEOCODING'
    | 'STORING'
    | 'DECISION_GATE'
    | 'NOTIFYING'
    | 'COMPLETE';
  data: {
    audio?: string;
    extraction?: any;
    location?: { latitude: number; longitude: number };
    geoEnriched?: any;
    mongoStored?: any;
    notifications?: any[];
    surveillanceData?: any;
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
  ) {
    this.checkAgentHealth();
  }

  /**
   * Start a complete encounter workflow through the orchestrator.
   * This orchestrates all agents in sequence: Intake → Geo → Data → Notify → Surveillance
   */
  async startEncounter(params: {
    audio_base64: string;
    latitude?: number;
    longitude?: number;
    chw_id?: string;
    sessionId?: string;
  }): Promise<EncounterSession> {
    const sessionId = params.sessionId || `encounter-${Date.now()}`;

    const session: EncounterSession = {
      sessionId,
      state: 'IDLE',
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

    try {
      // Step 1: Intake Agent - Extract clinical data from audio
      session.state = 'LISTENING';
      this.sessionUpdates.next(session);

      const extractionResult = await this.intakeAgent.extractClinicalData({
        audio_base64: params.audio_base64,
      });
      session.data.extraction = extractionResult;
      session.state = 'EXTRACTING';
      this.sessionUpdates.next(session);

      // Step 2: Geo Agent - Enrich with location data
      if (params.latitude !== undefined && params.longitude !== undefined) {
        session.state = 'GEOCODING';
        this.sessionUpdates.next(session);

        const geoResult = await this.geoAgent.enrichEncounter({
          encounter_json: extractionResult,
          latitude: params.latitude,
          longitude: params.longitude,
        });
        session.data.geoEnriched = geoResult;
      }

      // Step 3: Data Agent - Store in MongoDB with embeddings
      session.state = 'STORING';
      this.sessionUpdates.next(session);

      const storedResult = await this.dataAgent.insertEncounter({
        enriched_encounter: session.data.geoEnriched || extractionResult,
      });
      session.data.mongoStored = storedResult;

      // Step 4: Decision Gate - Wait for human-in-the-loop confirmation
      session.state = 'DECISION_GATE';
      this.sessionUpdates.next(session);
      // Gate confirmation handled by UI component

      // Step 5: Notify Agent - Send notifications
      session.state = 'NOTIFYING';
      this.sessionUpdates.next(session);

      if (session.data.geoEnriched?.alert_needed) {
        const notifyResult = await this.notifyAgent.sendNotification({
          title: 'Urgent Alert',
          message: session.data.geoEnriched.alert_message,
          recipients: session.data.geoEnriched.alert_recipients || [],
          encounter_id: storedResult?.id,
        });
        session.data.notifications = [notifyResult];
      }

      // Step 6: Surveillance Agent - Trigger post-encounter surveillance check
      const surveillanceResult =
        await this.surveillanceAgent.triggerSurveillance({
          county: session.data.geoEnriched?.admin_hierarchy?.county ?? '',
          immediate: false,
        });
      session.data.surveillanceData = surveillanceResult;

      session.state = 'COMPLETE';
      this.sessionUpdates.next(session);

      return session;
    } catch (error) {
      session.error = error instanceof Error ? error.message : 'Unknown error';
      session.state = 'IDLE';
      this.sessionUpdates.next(session);
      throw error;
    }
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
   * Confirm or decline a human-in-the-loop decision gate
   */
  async confirmEncounterDecision(
    sessionId: string,
    confirmed: boolean,
  ): Promise<void> {
    const session = this.activeSessions.get(sessionId);
    if (!session) throw new Error(`Session ${sessionId} not found`);

    await this.intakeAgent.confirmDecision(sessionId, confirmed);

    if (!confirmed) {
      session.state = 'COMPLETE';
      this.sessionUpdates.next(session);
    }
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
