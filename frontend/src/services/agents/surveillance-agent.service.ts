/**
 * Surveillance Agent Service
 *
 * All methods map to real orchestrator endpoints.
 * Broken/missing endpoints from earlier version replaced with correct routes.
 */

import { Injectable } from '@angular/core';
import { ApiService } from '../api.service';

export interface SurveillanceAlert {
  alert_id: string;
  alert_type:
    | 'outbreak'
    | 'silent_pandemic'
    | 'cross_county_spread'
    | 'chw_outreach_gap'
    | string;
  syndrome: string;
  location?: { county: string; ward?: string };
  count?: number;
  percent_above_baseline?: number;
  detected_at?: string;
  status?: string;
  risk_level?: string;
  escalation_level?: string;
  recommended_actions?: string[];
  [key: string]: any;
}

@Injectable({ providedIn: 'root' })
export class SurveillanceAgentService {
  constructor(private api: ApiService) {}

  /**
   * Trigger immediate outbreak detection for a county.
   * POST /tool/trigger_surveillance
   */
  async triggerSurveillance(request: {
    county: string;
    lat?: number;
    lng?: number;
    immediate?: boolean;
    hours?: number;
  }): Promise<any> {
    return this.api.triggerSurveillance(request);
  }

  /**
   * Scan for silent pandemic signals (persistent weekly upward trend).
   * POST /tool/silent_pandemic_scan
   */
  async silentPandemicScan(request: {
    county: string;
    weeks?: number;
  }): Promise<any> {
    return this.api.silentPandemicScan(request);
  }

  /**
   * Get active outbreak alerts, optionally filtered by county.
   * Replaces the broken /tool/get_region_alerts.
   * POST /tool/query_active_alerts
   */
  async getRegionAlerts(request: {
    region: string;
  }): Promise<SurveillanceAlert[]> {
    const res: any = await this.api.queryActiveAlerts({
      county: request.region,
    });
    return res?.alerts ?? [];
  }

  /**
   * Detect cross-county spread of a syndrome.
   * POST /tool/cross_county_spread
   */
  async detectCrossCountySpread(request: {
    syndrome: string;
    hours?: number;
  }): Promise<any> {
    return this.api.crossCountySpread(request);
  }

  /**
   * Get county surveillance stats (encounters, alerts, follow-ups, active CHWs).
   * Replaces the broken /tool/surveillance_report.
   * POST /tool/get_county_stats
   */
  async getSurveillanceReport(request: { county: string }): Promise<any> {
    return this.api.getCountyStats(request.county);
  }

  /**
   * Identify wards with low CHW encounter submissions.
   * Replaces the broken /tool/analyze_symptom_trends.
   * POST /tool/chw_outreach_gaps
   */
  async analyzeSymptomTrends(request: {
    county: string;
    days?: number;
  }): Promise<any> {
    return this.api.chwOutreachGaps({
      county: request.county,
      days: request.days,
    });
  }

  /**
   * Detect cross-county spread clusters.
   * Replaces the broken /tool/check_disease_clusters.
   * POST /tool/cross_county_spread
   */
  async checkDiseaseClusters(request: {
    disease?: string;
    hours?: number;
  }): Promise<any> {
    return this.api.crossCountySpread({
      syndrome: request.disease ?? '',
      hours: request.hours,
    });
  }

  /**
   * Get surveillance dashboard data.
   * GET /surveillance/dashboard
   */
  async getDashboardData(): Promise<any> {
    return this.api.get('/surveillance/dashboard');
  }

  /**
   * Recalculate 4-week rolling baselines.
   * POST /tool/update_baselines
   */
  async updateBaselines(county?: string): Promise<any> {
    return this.api.updateBaselines({ county });
  }

  async healthCheck(): Promise<boolean> {
    try {
      await this.api.healthSurveillance();
      return true;
    } catch {
      return false;
    }
  }
}
