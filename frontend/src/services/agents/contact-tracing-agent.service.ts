/**
 * Contact Tracing Agent Service
 *
 * Connects to the orchestrator's contact tracing endpoints:
 *   POST /tool/trace_contacts          — initiate trace
 *   GET  /tool/trace_status/{id}       — get trace with histogram
 *   POST /tool/update_contact_status   — update contact visit
 *   GET  /tool/active_traces           — list active traces
 *   POST /tool/resolve_trace           — mark trace resolved
 *   GET  /health/contact_tracing       — health check
 */

import { Injectable } from '@angular/core';
import { ApiService } from '../api.service';

export interface ContactTrace {
  trace_id: string;
  syndrome: string;
  status: 'active' | 'resolved' | 'escalated';
  total_contacts: number;
  contacted_count: number;
  confirmed_cases: number;
  escalation_level?: string;
  created_at: string;
  index_case: {
    triage_color: string;
    location: { county: string; ward: string };
    timestamp: string;
  };
  analytics?: {
    completion_rate_pct: number;
    secondary_attack_rate: number;
    status_histogram: Record<string, number>;
    tier_histogram: Record<string, number>;
    overdue: number;
  };
  contacts?: ContactRecord[];
  history?: TraceHistoryEvent[];
  [key: string]: any;
}

export interface ContactRecord {
  contact_id: string;
  risk_tier: 'HOUSEHOLD' | 'COMMUNITY' | 'FACILITY' | 'UNKNOWN';
  status: 'identified' | 'contacted' | 'assessed' | 'cleared' | 'confirmed';
  confirmed_case: boolean;
  location: { county: string; ward: string };
  assigned_chw?: string;
  due_date?: string;
  notes?: string;
  [key: string]: any;
}

export interface TraceHistoryEvent {
  event: string;
  timestamp: string;
  by: string;
  detail?: string;
}

@Injectable({ providedIn: 'root' })
export class ContactTracingAgentService {
  constructor(private api: ApiService) {}

  /**
   * Initiate a contact trace for an encounter or outbreak cluster.
   * POST /tool/trace_contacts
   */
  async initiateTrace(request: {
    encounter_id?: string;
    alert_id?: string;
    initiated_by?: string;
  }): Promise<ContactTrace> {
    return this.api.post('/tool/trace_contacts', request);
  }

  /**
   * Get full trace status with analytics histogram.
   * GET /tool/trace_status/{trace_id}
   */
  async getTraceStatus(traceId: string): Promise<ContactTrace> {
    return this.api.get(`/tool/trace_status/${encodeURIComponent(traceId)}`);
  }

  /**
   * Update a contact's visit status.
   * POST /tool/update_contact_status
   */
  async updateContactStatus(request: {
    trace_id: string;
    contact_id: string;
    status: 'contacted' | 'assessed' | 'cleared' | 'confirmed';
    new_encounter_id?: string;
    notes?: string;
    chw_id?: string;
  }): Promise<any> {
    return this.api.post('/tool/update_contact_status', request);
  }

  /**
   * List active traces, optionally filtered by county/syndrome.
   * GET /tool/active_traces
   */
  async getActiveTraces(
    filters: {
      county?: string;
      syndrome?: string;
      limit?: number;
    } = {},
  ): Promise<{ traces: ContactTrace[]; count: number }> {
    const params = new URLSearchParams();
    if (filters.county) params.set('county', filters.county);
    if (filters.syndrome) params.set('syndrome', filters.syndrome);
    if (filters.limit) params.set('limit', String(filters.limit));
    const qs = params.toString();
    return this.api.get(`/tool/active_traces${qs ? '?' + qs : ''}`);
  }

  /**
   * Resolve a completed trace.
   * POST /tool/resolve_trace
   */
  async resolveTrace(traceId: string, notes = ''): Promise<any> {
    return this.api.post('/tool/resolve_trace', {
      trace_id: traceId,
      resolution_notes: notes,
    });
  }

  async healthCheck(): Promise<boolean> {
    try {
      await this.api.get('/health/contact_tracing');
      return true;
    } catch {
      return false;
    }
  }
}
