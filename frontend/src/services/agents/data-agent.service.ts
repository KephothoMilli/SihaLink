/**
 * Data Agent Service
 * 
 * Stores and retrieves encounters from MongoDB with vector embeddings.
 * Enables semantic search and trend analysis on clinical data.
 */

import { Injectable } from '@angular/core';
import { ApiService } from '../api.service';

export interface StoredEncounter {
  id: string;
  encounter_json: any;
  vector_embedding: number[];
  timestamp: number;
  chw_id?: string;
  facilities_recommended?: string[];
  metadata?: any;
}

export interface SearchQuery {
  query: string;
  limit?: number;
  location_filter?: { latitude: number; longitude: number; radius_km: number };
}

export interface SearchResult {
  encounters: StoredEncounter[];
  total_count: number;
  relevance_scores: number[];
}

@Injectable({
  providedIn: 'root'
})
export class DataAgentService {
  constructor(private api: ApiService) { }

    /**
    * Insert a new encounter into MongoDB with vector embedding
    */
    async insertEncounter(request: { enriched_encounter: any }): Promise<StoredEncounter> {
      return this.api.insertEncounter(request);
    }

  /**
   * Search encounters by semantic similarity
   */
  async searchEncounters(query: SearchQuery): Promise<SearchResult> {
    return this.api.post('/tool/search_encounters', {
      query: query.query,
      limit: query.limit || 10,
      location_filter: query.location_filter,
    });
  }

  /**
   * Get encounter by ID
   */
  async getEncounter(encounterId: string): Promise<StoredEncounter> {
    return this.api.get(`/encounters/${encounterId}`);
  }

  /**
   * Get all encounters for a CHW
   */
  async getEncountersByChw(chwId: string): Promise<StoredEncounter[]> {
    return this.api.get(`/encounters/chw/${chwId}`);
  }

  /**
   * Get trend analysis for encounters in a region
   */
  async getTrendAnalysis(request: {
    region?: string;
    time_range_days?: number;
    symptom_filter?: string[];
  }): Promise<any> {
    return this.api.post('/tool/trend_analysis', request);
  }

  /**
   * Delete an encounter (with proper audit trail)
   */
  async deleteEncounter(encounterId: string): Promise<void> {
    return this.api.post(`/encounters/${encounterId}/delete`, {});
  }

  /**
   * Update encounter metadata
   */
  async updateEncounter(encounterId: string, updates: any): Promise<StoredEncounter> {
    return this.api.post(`/encounters/${encounterId}/update`, {
      updates,
    });
  }

  /**
   * Check if Data Agent is available
   */
  async healthCheck(): Promise<boolean> {
    try {
      return await this.api.get('/health/data');
    } catch {
      return false;
    }
  }
}
