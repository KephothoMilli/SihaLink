/**
 * Surveillance Agent UI Component
 *
 * Interface for epidemiological surveillance and public health monitoring.
 * All method calls aligned to the refactored SurveillanceAgentService signatures.
 */

import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import {
  SurveillanceAgentService,
  SurveillanceAlert,
} from '../../../services/agents/surveillance-agent.service';

@Component({
  selector: 'app-surveillance-agent',
  templateUrl: './surveillance-agent.component.html',
  styleUrl: './surveillance-agent.component.scss',
  standalone: true,
  imports: [CommonModule, FormsModule],
})
export class SurveillanceAgentComponent implements OnInit {
  readonly Math = Math;

  selectedRegion = '';
  selectedSymptom = '';
  regionAlerts: SurveillanceAlert[] = [];
  dashboardData: any = null;
  trendAnalysis: any = null;
  clusterData: any = null;

  isLoading = false;
  error: string | null = null;
  activeTab: 'alerts' | 'trends' | 'clusters' | 'dashboard' = 'dashboard';

  // Days range for trend / alert queries
  trendDays = 30;

  constructor(private surveillanceAgent: SurveillanceAgentService) {}

  ngOnInit() {
    this.loadDashboard();
  }

  async loadDashboard() {
    this.isLoading = true;
    this.error = null;
    try {
      this.dashboardData = await this.surveillanceAgent.getDashboardData();
    } catch (err) {
      this.error =
        err instanceof Error ? err.message : 'Failed to load dashboard';
    } finally {
      this.isLoading = false;
    }
  }

  /** Get active alerts for the selected region (county). */
  async getRegionAlerts() {
    if (!this.selectedRegion.trim()) {
      this.error = 'Please select a region';
      return;
    }
    this.isLoading = true;
    this.error = null;
    try {
      // getRegionAlerts expects { region: string }
      this.regionAlerts = await this.surveillanceAgent.getRegionAlerts({
        region: this.selectedRegion,
      });
      this.activeTab = 'alerts';
    } catch (err) {
      this.error = err instanceof Error ? err.message : 'Failed to get alerts';
    } finally {
      this.isLoading = false;
    }
  }

  /** Analyse CHW outreach gaps for the selected county (replaces broken analyzeSymptomTrends). */
  async analyzeSymptomTrends() {
    if (!this.selectedRegion.trim()) {
      this.error = 'Please select a county';
      return;
    }
    this.isLoading = true;
    this.error = null;
    try {
      // analyzeSymptomTrends expects { county: string; days?: number }
      this.trendAnalysis = await this.surveillanceAgent.analyzeSymptomTrends({
        county: this.selectedRegion,
        days: this.trendDays,
      });
      this.activeTab = 'trends';
    } catch (err) {
      this.error =
        err instanceof Error ? err.message : 'Failed to analyse trends';
    } finally {
      this.isLoading = false;
    }
  }

  /** Detect cross-county spread clusters for the selected symptom. */
  async checkDiseaseClusters() {
    this.isLoading = true;
    this.error = null;
    try {
      // checkDiseaseClusters expects { disease?: string; hours?: number }
      this.clusterData = await this.surveillanceAgent.checkDiseaseClusters({
        disease: this.selectedSymptom || undefined,
      });
      this.activeTab = 'clusters';
    } catch (err) {
      this.error =
        err instanceof Error ? err.message : 'Failed to check clusters';
    } finally {
      this.isLoading = false;
    }
  }

  getAlertColor(severity: string): string {
    switch (severity) {
      case 'critical':
        return '#d32f2f';
      case 'high':
        return '#f57c00';
      case 'medium':
        return '#fbc02d';
      default:
        return '#388e3c';
    }
  }

  getRiskColor(level: string): string {
    const l = (level ?? '').toUpperCase();
    if (l === 'HIGH' || l === 'CRITICAL' || l === 'RED') return '#d32f2f';
    if (l === 'MEDIUM' || l === 'YELLOW' || l === 'ORANGE') return '#f57c00';
    if (l === 'LOW' || l === 'GREEN') return '#388e3c';
    return '#0288d1';
  }

  getAlertIcon(syndrome: string): string {
    const s = (syndrome ?? '').toLowerCase();
    if (s.includes('ebola') || s.includes('hemorrhagic')) return 'emergency';
    if (s.includes('cholera') || s.includes('diarrhea')) return 'water_drop';
    if (
      s.includes('respiratory') ||
      s.includes('pneumonia') ||
      s.includes('covid')
    )
      return 'pulmonology';
    if (s.includes('measles') || s.includes('rash')) return 'sick';
    if (s.includes('malaria') || s.includes('fever')) return 'thermometer';
    if (s.includes('malnutrition')) return 'monitor_weight';
    return 'coronavirus';
  }

  getSyndromeColor(syndrome: string): string {
    const palette: Record<string, string> = {
      measles: '#d32f2f',
      cholera: '#1565c0',
      acute_respiratory_infection: '#6a1b9a',
      acute_febrile_illness: '#e65100',
      malaria: '#2e7d32',
      tuberculosis: '#4e342e',
      pneumonia: '#0277bd',
      ebola: '#b71c1c',
      dengue: '#f9a825',
      typhoid: '#558b2f',
      malnutrition_severe: '#4527a0',
      meningitis: '#ad1457',
    };
    return palette[syndrome] ?? '#0288d1';
  }

  getBreakdownPct(count: number, breakdown: Array<{ count: number }>): number {
    const max = Math.max(...breakdown.map((b) => b.count), 1);
    return Math.round((count / max) * 100);
  }
}
