/**
 * SihaLink API Service
 * Wraps all calls to the Google Agent Runtime (Orchestrator) backend.
 *
 * Base URL resolution order:
 *   1. VITE_API_URL env var (set at build time for production)
 *   2. http://localhost:8000 (local dev — proxied by Vite)
 *
 * All methods return Promises. Errors surface as thrown Error objects
 * with the HTTP status + body included in the message.
 */

import { Injectable } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private base: string;

  constructor() {
    this.base = (
      (import.meta as any).env?.VITE_API_URL || 'http://localhost:8000'
    ).replace(/\/$/, '');
  }

  // ── HTTP primitives ────────────────────────────────────────────────────────

  public async post<T = any>(path: string, body: any = {}): Promise<T> {
    const res = await fetch(`${this.base}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`${res.status} ${res.statusText}: ${text}`);
    }
    return res.json();
  }

  public async get<T = any>(path: string): Promise<T> {
    const res = await fetch(`${this.base}${path}`);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.json();
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // ENCOUNTER LIFECYCLE
  // ═══════════════════════════════════════════════════════════════════════════

  /**
   * Kick off the full encounter pipeline via the unified state-machine endpoint.
   * Supports audio, text, and form payloads — the backend differentiates automatically.
   */
  startEncounter(body: {
    session_id: string;
    audio_base64?: string;
    form_data?: Record<string, any>;
    telegram_payload?: Record<string, any>;
    latitude?: number;
    longitude?: number;
    chw_id?: string;
  }) {
    return this.post('/encounter/start', body);
  }

  /** Poll the current state machine state for a session. */
  getEncounterStatus(sessionId: string) {
    return this.get(`/encounter/${sessionId}/status`);
  }

  /** CHV taps Confirm or Decline on the DECISION_GATE. */
  confirmEncounter(sessionId: string, confirmed: boolean) {
    return this.post(`/encounter/${sessionId}/confirm`, { confirmed });
  }

  /**
   * Submit a clarification answer for a session paused at CLARIFICATION_GATE.
   * Resolves the asyncio.Future in the state machine so the lifecycle continues.
   */
  clarifyEncounter(sessionId: string, answer: string) {
    return this.post(`/encounter/${sessionId}/clarify`, { answer });
  }

  /**
   * Unified gate-resolution for Telegram-style chat_id sessions.
   * The backend matches the most recent tg-<chat_id>-<ts> session.
   */
  respondToGate(chatId: string, text: string, confirm?: boolean) {
    return this.post('/encounter/respond', { chat_id: chatId, text, confirm });
  }

  // ── Individual tool endpoints ─────────────────────────────────────────────

  /** Extract clinical data from base64 audio (Gemini Live API). */
  extractClinicalData(body: {
    audio_base64: string;
    clarification_answers?: string[];
  }) {
    return this.post('/tool/route_to_intake', {
      session_id: `extract-${Date.now()}`,
      audio_base64: body.audio_base64,
      clarification_answers: body.clarification_answers,
    });
  }

  /** Submit a structured clinical web form to the intake pipeline. */
  intakeForm(formData: {
    chief_complaint: string;
    symptoms?: string[];
    age_value?: number;
    age_unit?: string;
    sex?: string;
    temperature_c?: number;
    respiratory_rate?: number;
    heart_rate?: number;
    duration_days?: number;
    syndrome_hint?: string;
    language_hint?: string;
    county?: string;
  }) {
    return this.post('/intake/form', {
      session_id: `form-${Date.now()}`,
      form_data: formData,
    });
  }

  /** Relay a CHV Telegram message through the intake pipeline. */
  intakeTelegram(body: {
    chw_id: string;
    message_text: string;
    audio_base64?: string;
    language_hint?: string;
  }) {
    return this.post('/intake/telegram', {
      session_id: `tg-${body.chw_id}-${Date.now()}`,
      ...body,
    });
  }

  /** Refine a previous extraction with a CHV clarification answer. */
  clarifyExtraction(body: {
    original_extraction: any;
    clarification_answer: string;
  }) {
    return this.post('/tool/clarify_extraction', body);
  }

  /** Enrich an encounter with admin hierarchy + nearest facilities. */
  enrichEncounter(body: {
    encounter_json: any;
    latitude: number;
    longitude: number;
  }) {
    return this.post('/tool/route_to_geo', body);
  }

  /** Store a geo-enriched encounter in MongoDB with vector embedding. */
  insertEncounter(body: { enriched_encounter: any }) {
    return this.post('/tool/route_to_data', body);
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // ALERTS
  // ═══════════════════════════════════════════════════════════════════════════

  /** Query active outbreak alerts, optionally filtered by county. */
  queryActiveAlerts(body: { county?: string } = {}) {
    return this.post('/tool/query_active_alerts', body);
  }

  /** Acknowledge an alert (district officer action). */
  updateAlertStatus(body: {
    alert_id: string;
    status: 'acknowledged' | 'resolved';
    user_id?: string;
  }) {
    return this.post('/tool/update_alert_status', body);
  }

  /** Resolve an alert with optional notes. */
  resolveAlert(body: { alert_id: string; notes?: string; user_id?: string }) {
    return this.post('/tool/resolve_alert', body);
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // REFERRALS
  // ═══════════════════════════════════════════════════════════════════════════

  /** Query patient referrals with optional county and status filters. */
  queryReferrals(
    body: {
      county?: string;
      status?: 'pending' | 'accepted' | 'redirected' | 'completed';
      limit?: number;
    } = {},
  ) {
    return this.post('/tool/query_referrals', body);
  }

  /** Update referral status (facility accepts or redirects). */
  updateReferralStatus(body: {
    referral_id: string;
    status: 'accepted' | 'redirected' | 'completed' | 'cancelled';
    notes?: string;
  }) {
    return this.post('/tool/update_referral_status', body);
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // PATIENT FOLLOW-UPS
  // ═══════════════════════════════════════════════════════════════════════════

  /** Get pending follow-up tasks for a CHW. */
  getChwFollowUps(chwId: string, overdueOnly = false) {
    return this.get(
      `/tool/follow_ups/${encodeURIComponent(chwId)}?overdue_only=${overdueOnly}`,
    );
  }

  /** Get all pending follow-ups for a county (supervisor view). */
  getCountyFollowUps(county: string, overdueOnly = false) {
    return this.post('/tool/get_pending_follow_ups', {
      county,
      overdue_only: overdueOnly,
    });
  }

  /** Mark a follow-up as completed with clinical outcome. */
  completeFollowUp(body: {
    follow_up_id: string;
    outcome: 'improved' | 'stable' | 'deteriorated' | 'referred' | 'deceased';
    notes?: string;
    chw_id?: string;
  }) {
    return this.post('/tool/complete_follow_up', body);
  }

  /** Reschedule a follow-up to a new date. */
  rescheduleFollowUp(body: {
    follow_up_id: string;
    days_from_now: number;
    reason?: string;
  }) {
    return this.post('/tool/reschedule_follow_up', body);
  }

  /** Get follow-up completion stats for a county (pending / completed / overdue). */
  getFollowUpSummary(county: string) {
    return this.get(`/tool/follow_up_summary/${encodeURIComponent(county)}`);
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // PROTOCOLS
  // ═══════════════════════════════════════════════════════════════════════════

  /** Retrieve the active WHO/MoH response protocol for a syndrome. */
  getProtocol(syndrome: string, county?: string) {
    const params = county ? `?county=${encodeURIComponent(county)}` : '';
    return this.get(`/tool/protocol/${encodeURIComponent(syndrome)}${params}`);
  }

  /** Full-text Atlas Search across all protocols. */
  searchProtocols(query: string, limit = 5) {
    return this.post('/tool/search_protocols', { query, limit });
  }

  /** List all active protocols, optionally filtered by county. */
  listProtocols(county?: string) {
    return this.post('/tool/list_protocols', { county });
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // CHW REGISTRY
  // ═══════════════════════════════════════════════════════════════════════════

  /** Register or update a CHW in the registry. */
  registerChw(body: {
    name: string;
    county: string;
    ward: string;
    telegram_id?: number;
    phone?: string;
    languages?: string[];
  }) {
    return this.post('/tool/register_chw', body);
  }

  /** List active CHWs in a county, optionally filtered by ward. */
  listChws(county: string, ward?: string) {
    const params = ward ? `?ward=${encodeURIComponent(ward)}` : '';
    return this.get(`/tool/chws/${encodeURIComponent(county)}${params}`);
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // SURVEILLANCE
  // ═══════════════════════════════════════════════════════════════════════════

  /** Trigger outbreak detection for a county. */
  triggerSurveillance(body: {
    county: string;
    lat?: number;
    lng?: number;
    immediate?: boolean;
    hours?: number;
  }) {
    return this.post('/tool/trigger_surveillance', body);
  }

  /**
   * Scan for silent pandemic signals — syndromes with a persistent upward
   * trend over multiple weeks that never trigger a single-week spike.
   */
  silentPandemicScan(body: { county: string; weeks?: number }) {
    return this.post('/tool/silent_pandemic_scan', body);
  }

  /** Detect cross-county spread of a syndrome. */
  crossCountySpread(body: { syndrome: string; hours?: number }) {
    return this.post('/tool/cross_county_spread', body);
  }

  /** Identify wards with low CHW encounter submissions. */
  chwOutreachGaps(body: { county: string; days?: number }) {
    return this.post('/tool/chw_outreach_gaps', body);
  }

  /** Recalculate 4-week rolling baselines for a county. */
  updateBaselines(body: { county?: string } = {}) {
    return this.post('/tool/update_baselines', body);
  }

  /**
   * Get county surveillance stats:
   * encounters_today, active_alerts, pending_followups, active_chws.
   */
  getCountyStats(county: string) {
    return this.post('/tool/get_county_stats', { county });
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // OFFLINE SYNC
  // ═══════════════════════════════════════════════════════════════════════════

  /** Batch-sync encounters queued while the CHV device was offline. */
  syncOfflineEncounters(encounters: any[]) {
    return this.post('/tool/sync_offline_encounters', { encounters });
  }

  /** Process the full offline queue when connectivity returns. */
  processOfflineQueue() {
    return this.post('/tool/process_offline_queue', {});
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // HEALTH
  // ═══════════════════════════════════════════════════════════════════════════

  health() {
    return this.get('/health');
  }
  healthData() {
    return this.get('/health/data');
  }
  healthGeo() {
    return this.get('/health/geo');
  }
  healthIntake() {
    return this.get('/health/intake');
  }
  healthNotify() {
    return this.get('/health/notify');
  }
  healthSurveillance() {
    return this.get('/health/surveillance');
  }

  healthContactTracing() {
    return this.get('/health/contact_tracing');
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // CONTACT TRACING
  // ═══════════════════════════════════════════════════════════════════════════

  /** Initiate a contact trace for an encounter or outbreak cluster. */
  traceContacts(body: {
    encounter_id?: string;
    alert_id?: string;
    initiated_by?: string;
  }) {
    return this.post('/tool/trace_contacts', body);
  }

  /** Get full trace status with analytics histogram. */
  getTraceStatus(traceId: string) {
    return this.get(`/tool/trace_status/${encodeURIComponent(traceId)}`);
  }

  /** Update a contact's visit status. */
  updateContactStatus(body: {
    trace_id: string;
    contact_id: string;
    status: 'contacted' | 'assessed' | 'cleared' | 'confirmed';
    new_encounter_id?: string;
    notes?: string;
    chw_id?: string;
  }) {
    return this.post('/tool/update_contact_status', body);
  }

  /** List active traces, optionally filtered by county/syndrome. */
  getActiveTraces(
    params: {
      county?: string;
      syndrome?: string;
      limit?: number;
    } = {},
  ) {
    const qs = new URLSearchParams();
    if (params.county) qs.set('county', params.county);
    if (params.syndrome) qs.set('syndrome', params.syndrome);
    if (params.limit) qs.set('limit', String(params.limit));
    const q = qs.toString();
    return this.get(`/tool/active_traces${q ? '?' + q : ''}`);
  }

  /** Resolve a completed contact trace. */
  resolveTrace(body: {
    trace_id: string;
    resolved_by?: string;
    resolution_notes?: string;
  }) {
    return this.post('/tool/resolve_trace', body);
  }

  // ═════════════════════════════════════════════════════════════════════════════
  // NOTIFICATIONS
  // ═════════════════════════════════════════════════════════════════════════════

  /** Send a notification to recipients */
  sendNotification(body: {
    title: string;
    message: string;
    recipients: string[];
    encounter_id?: string;
    priority?: 'low' | 'medium' | 'high' | 'critical';
    action_url?: string;
    metadata?: any;
  }) {
    return this.post('/tool/route_to_notify', body);
  }

  /** Get notification history for an encounter */
  getNotificationHistory(encounterId: string) {
    return this.get(
      `/notifications/encounter/${encodeURIComponent(encounterId)}`,
    );
  }

  /** Get delivery status of a notification */
  getNotificationStatus(notificationId: string) {
    return this.get(`/notifications/${encodeURIComponent(notificationId)}`);
  }

  /** Register a recipient (CHW, supervisor, etc.) */
  registerRecipient(body: {
    telegram_id?: string;
    phone_number?: string;
    name: string;
    role: string;
  }) {
    return this.post('/tool/register_recipient', body);
  }

  /** Get list of registered recipients */
  getRecipients() {
    return this.get('/notifications/recipients');
  }

  // ═════════════════════════════════════════════════════════════════════════════
  // AGENT OBSERVABILITY (LOGS)
  // ═════════════════════════════════════════════════════════════════════════════

  /** Fetch recent agent decision-making logs */
  getAgentLogs(sessionId?: string, limit: number = 50) {
    const params = new URLSearchParams({ limit: limit.toString() });
    if (sessionId) params.append('session_id', sessionId);
    return this.get(`/swarm/agent_logs?${params.toString()}`);
  }

  /** Search agent logs using Atlas Vector Search */
  searchAgentLogs(query: string, limit: number = 10) {
    const params = new URLSearchParams({ query, limit: limit.toString() });
    return this.get(`/swarm/agent_logs/search?${params.toString()}`);
  }
}
