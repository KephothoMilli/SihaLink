/**
 * Surveillance Agent UI Component
 *
 * Interface for epidemiological surveillance and public health monitoring
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
  // Expose Math to the template
  readonly Math = Math;

  selectedRegion: string = '';
  selectedSymptom: string = '';
  regionAlerts: SurveillanceAlert[] = [];
  dashboardData: any = null;
  trendAnalysis: any = null;
  clusterData: any = null;

  isLoading = false;
  error: string | null = null;
  activeTab: 'alerts' | 'trends' | 'clusters' | 'dashboard' = 'dashboard';

  // datetime-local inputs need ISO string format
  startDate: string = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000)
    .toISOString()
    .slice(0, 16);
  endDate: string = new Date().toISOString().slice(0, 16);

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

  async getRegionAlerts() {
    if (!this.selectedRegion.trim()) {
      this.error = 'Please select a region';
      return;
    }

    this.isLoading = true;
    this.error = null;

    try {
      this.regionAlerts = await this.surveillanceAgent.getRegionAlerts({
        region: this.selectedRegion,
        start_date: new Date(this.startDate).getTime(),
        end_date: new Date(this.endDate).getTime(),
      });
      this.activeTab = 'alerts';
    } catch (err) {
      this.error = err instanceof Error ? err.message : 'Failed to get alerts';
    } finally {
      this.isLoading = false;
    }
  }

  async analyzeSymptomTrends() {
    if (!this.selectedSymptom.trim()) {
      this.error = 'Please enter a symptom';
      return;
    }

    this.isLoading = true;
    this.error = null;

    try {
      this.trendAnalysis = await this.surveillanceAgent.analyzeSymptomTrends({
        symptom: this.selectedSymptom,
        region: this.selectedRegion,
        days: Math.floor(
          (new Date(this.endDate).getTime() -
            new Date(this.startDate).getTime()) /
            (24 * 60 * 60 * 1000),
        ),
      });
      this.activeTab = 'trends';
    } catch (err) {
      this.error =
        err instanceof Error ? err.message : 'Failed to analyze trends';
    } finally {
      this.isLoading = false;
    }
  }

  async checkDiseaseClusters() {
    this.isLoading = true;
    this.error = null;

    try {
      this.clusterData = await this.surveillanceAgent.checkDiseaseClusters({
        region: this.selectedRegion,
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
