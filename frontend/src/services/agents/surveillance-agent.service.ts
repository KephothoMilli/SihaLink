/**
 * Surveillance Agent Service
 * 
 * Processes encounter data for epidemiological surveillance.
 * Triggers alerts for disease outbreaks, trend anomalies, and public health patterns.
 */

import { Injectable } from '@angular/core';
import { ApiService } from '../api.service';

export interface SurveillanceAlert {
    alert_id: string;
    alert_type: 'outbreak' | 'anomaly' | 'trend' | 'cluster';
    title: string;
    description: string;
    severity: 'low' | 'medium' | 'high' | 'critical';
    affected_region?: string;
    case_count?: number;
    threshold?: number;
    actual_value?: number;
    recommendations: string[];
    created_at: number;
}

export interface SurveillanceReport {
    report_id: string;
    period: { start: number; end: number };
    total_encounters: number;
    unique_symptoms: string[];
    top_symptoms: { symptom: string; count: number }[];
    alerts: SurveillanceAlert[];
    trend_analysis: any;
}

@Injectable({
    providedIn: 'root'
})
export class SurveillanceAgentService {
    constructor(private api: ApiService) { }

    /**
     * Trigger surveillance analysis on an encounter
     */
    async triggerSurveillance(request: {
        encounter_id?: string;
        encounter_data: any;
    }): Promise<SurveillanceAlert[]> {
        return this.api.post('/tool/trigger_surveillance', {
            encounter_id: request.encounter_id,
            encounter_data: request.encounter_data,
        });
    }

    /**
     * Get surveillance alerts for a region
     */
    async getRegionAlerts(request: {
        region: string;
        start_date?: number;
        end_date?: number;
        alert_types?: string[];
    }): Promise<SurveillanceAlert[]> {
        return this.api.post('/tool/get_region_alerts', request);
    }

    /**
     * Get surveillance report for a specific period
     */
    async getSurveillanceReport(request: {
        region?: string;
        start_date: number;
        end_date: number;
    }): Promise<SurveillanceReport> {
        return this.api.post('/tool/surveillance_report', request);
    }

    /**
     * Analyze symptom trends
     */
    async analyzeSymptomTrends(request: {
        symptom?: string;
        region?: string;
        days?: number;
    }): Promise<any> {
        return this.api.post('/tool/analyze_symptom_trends', {
            symptom: request.symptom,
            region: request.region,
            days: request.days || 30,
        });
    }

    /**
     * Check for disease clusters
     */
    async checkDiseaseClusters(request: {
        disease?: string;
        region?: string;
        radius_km?: number;
        time_window_hours?: number;
    }): Promise<any> {
        return this.api.post('/tool/check_disease_clusters', {
            disease: request.disease,
            region: request.region,
            radius_km: request.radius_km || 50,
            time_window_hours: request.time_window_hours || 168,
        });
    }

    /**
     * Get surveillance dashboard data
     */
    async getDashboardData(): Promise<any> {
        return this.api.get('/surveillance/dashboard');
    }

    /**
     * Export surveillance report
     */
    async exportReport(reportId: string, format: 'pdf' | 'csv' | 'json' = 'pdf'): Promise<Blob> {
        const response = await fetch(`${this.api['base']}/surveillance/reports/${reportId}/export?format=${format}`);
        if (!response.ok) throw new Error('Failed to export report');
        return response.blob();
    }

    /**
     * Check if Surveillance Agent is available
     */
    async healthCheck(): Promise<boolean> {
        try {
            return await this.api.get('/health/surveillance');
        } catch {
            return false;
        }
    }
}
