/**
 * Geo Agent Service
 *
 * Enriches encounters with geographic data:
 * - Admin hierarchy (district, sub-county, etc.)
 * - Nearest facilities and ETAs
 * - Health facility recommendations
 */

import { Injectable } from '@angular/core';
import { ApiService } from '../api.service';

export interface Location {
  latitude: number;
  longitude: number;
}

export interface Facility {
  id: string;
  name: string;
  type: string;
  distance_km: number;
  eta_minutes: number;
  contact?: string;
  has_transport?: boolean;
}

export interface GeoEnrichment {
  admin_hierarchy: {
    region?: string;
    district?: string;
    sub_county?: string;
    ward?: string;
    village?: string;
  };
  nearest_facilities: Facility[];
  recommended_facility: Facility;
  alert_needed: boolean;
  alert_message?: string;
  alert_recipients?: string[];
}

@Injectable({
  providedIn: 'root',
})
export class GeoAgentService {
  constructor(private api: ApiService) {}

  /**
   * Enrich an encounter with geographic data
   */
  async enrichEncounter(request: {
    encounter_json: any;
    latitude: number;
    longitude: number;
  }): Promise<GeoEnrichment> {
    return this.api.enrichEncounter(request);
  }

  /**
   * Find nearest health facilities for a location
   */
  async findNearestFacilities(
    location: Location,
    radius_km: number = 50,
  ): Promise<Facility[]> {
    return this.api.post('/tool/find_nearest_facilities', {
      latitude: location.latitude,
      longitude: location.longitude,
      radius_km,
    });
  }

  /**
   * Get administrative hierarchy for a location
   */
  async getAdminHierarchy(location: Location): Promise<any> {
    return this.api.post('/tool/get_admin_hierarchy', {
      latitude: location.latitude,
      longitude: location.longitude,
    });
  }

  /**
   * Calculate ETA to a specific facility
   */
  async getETAToFacility(
    from: Location,
    to: Location,
  ): Promise<{ distance_km: number; eta_minutes: number }> {
    return this.api.post('/tool/get_eta', {
      from_latitude: from.latitude,
      from_longitude: from.longitude,
      to_latitude: to.latitude,
      to_longitude: to.longitude,
    });
  }

  /**
   * Check if Geo Agent is available
   */
  async healthCheck(): Promise<boolean> {
    try {
      await this.api.healthGeo();
      return true;
    } catch {
      return false;
    }
  }
}
