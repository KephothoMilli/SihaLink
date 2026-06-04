/**
 * Data Agent Service
 *
 * All methods map to real orchestrator endpoints.
 * Broken routes from earlier version replaced with correct equivalents.
 */

import { Injectable } from '@angular/core';
import { ApiService } from '../api.service';

export interface StoredEncounter {
  id: string;
  encounter_id?: string;
  encounter_json?: any;
  timestamp?: number;
  chw_id?: string;
  [key: string]: any;
}

export interface SearchQuery {
  query: string;
  limit?: number;
  location_filter?: { latitude: number; longitude: number; radius_km: number };
}

@Injectable({ providedIn: 'root' })
export class DataAgentService {
  constructor(private api: ApiService) {}

  /** Insert a geo-enriched encounter into MongoDB. POST /tool/route_to_data */
  async insertEncounter(request: { enriched_encounter: any }): Promise<any> {
    return this.api.insertEncounter(request);
  }

  /** Vector/Atlas search across encounters. POST /tool/search_encounters */
  async searchEncounters(query: SearchQuery): Promise<any> {
    return this.api.post('/tool/search_encounters', {
      query: query.query,
      limit: query.limit ?? 10,
      location_filter: query.location_filter,
    });
  }

  /**
   * Get pending follow-ups for a CHW.
   * Replaces broken GET /encounters/{id} — use the real follow-ups endpoint.
   * GET /tool/follow_ups/{chw_id}
   */
  async getChwFollowUps(chwId: string, overdueOnly = false): Promise<any> {
    return this.api.getChwFollowUps(chwId, overdueOnly);
  }

  /**
   * Get county follow-up summary (pending / completed / overdue).
   * Replaces broken GET /encounters/chw/{id}.
   * GET /tool/follow_up_summary/{county}
   */
  async getFollowUpSummary(county: string): Promise<any> {
    return this.api.getFollowUpSummary(county);
  }

  /** Complete a follow-up task. POST /tool/complete_follow_up */
  async completeFollowUp(body: {
    follow_up_id: string;
    outcome: 'improved' | 'stable' | 'deteriorated' | 'referred' | 'deceased';
    notes?: string;
    chw_id?: string;
  }): Promise<any> {
    return this.api.completeFollowUp(body);
  }

  /** Reschedule a follow-up. POST /tool/reschedule_follow_up */
  async rescheduleFollowUp(body: {
    follow_up_id: string;
    days_from_now: number;
    reason?: string;
  }): Promise<any> {
    return this.api.rescheduleFollowUp(body);
  }

  /**
   * Get county surveillance stats — encounters, alerts, follow-ups, CHWs.
   * Replaces broken /tool/trend_analysis.
   * POST /tool/get_county_stats
   */
  async getCountyStats(county: string): Promise<any> {
    return this.api.getCountyStats(county);
  }

  /** Retrieve a protocol for a syndrome. GET /tool/protocol/{syndrome} */
  async getProtocol(syndrome: string, county?: string): Promise<any> {
    return this.api.getProtocol(syndrome, county);
  }

  /** Full-text search across protocols. POST /tool/search_protocols */
  async searchProtocols(query: string, limit = 5): Promise<any> {
    return this.api.searchProtocols(query, limit);
  }

  /** Batch-sync offline-queued encounters. POST /tool/sync_offline_encounters */
  async syncOfflineEncounters(encounters: any[]): Promise<any> {
    return this.api.syncOfflineEncounters(encounters);
  }

  async healthCheck(): Promise<boolean> {
    try {
      await this.api.healthData();
      return true;
    } catch {
      return false;
    }
  }
}
