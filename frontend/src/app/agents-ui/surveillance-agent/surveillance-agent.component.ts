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
  styleUrl: './surveillance-agent.component.css',
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
}
