/**
 * Dashboard Component
 *
 * Main dashboard showing orchestrator status and recent encounters
 */

import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { Observable } from 'rxjs';
import { RootAgentService } from '../../services/root-agent.service';

@Component({
  selector: 'app-dashboard',
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.css',
  standalone: true,
  imports: [CommonModule, RouterModule],
})
export class DashboardComponent implements OnInit {
  agentStatus$!: Observable<any>;
  activeSessions: any[] = [];
  sessionUpdates$!: Observable<any>;

  agents = [
    {
      name: 'Intake Agent',
      description: 'Extract clinical data from audio',
      route: '/agents/intake',
      icon: '🎤',
    },
    {
      name: 'Geo Agent',
      description: 'Enrich with location data',
      route: '/agents/geo',
      icon: '📍',
    },
    {
      name: 'Data Agent',
      description: 'Manage stored encounters',
      route: '/agents/data',
      icon: '💾',
    },
    {
      name: 'Notify Agent',
      description: 'Send alerts and notifications',
      route: '/agents/notify',
      icon: '📨',
    },
    {
      name: 'Surveillance Agent',
      description: 'Monitor public health trends',
      route: '/agents/surveillance',
      icon: '📊',
    },
    {
      name: 'Contact Tracing Agent',
      description: 'Trace & track exposed contacts',
      route: '/agents/contact-tracing',
      icon: '🔗',
    },
  ];

  constructor(private rootAgent: RootAgentService) {}

  ngOnInit() {
    this.agentStatus$ = this.rootAgent.agentStatus$;
    this.sessionUpdates$ = this.rootAgent.sessionUpdates$;
    this.loadSessions();
  }

  loadSessions() {
    this.activeSessions = this.rootAgent.getActiveSessions();
  }

  getStateColor(state: string): string {
    switch (state) {
      case 'COMPLETE':
        return 'var(--color-green)';
      case 'FAILED':
        return 'var(--color-red)';
      case 'DECISION_GATE':
        return 'var(--color-yellow)';
      case 'CLARIFICATION_GATE':
        return '#f59e0b';
      case 'OFFLINE_QUEUED':
        return '#6366f1';
      default:
        return 'var(--color-secondary)';
    }
  }

  getStateProgress(state: string): number {
    switch (state) {
      case 'IDLE':
        return 5;
      case 'LISTENING':
        return 15;
      case 'EXTRACTING':
        return 30;
      case 'CLARIFICATION_GATE':
        return 35;
      case 'GEOCODING':
        return 50;
      case 'STORING':
        return 65;
      case 'FOLLOW_UP_SCHEDULED':
        return 70;
      case 'ALERTING':
        return 75;
      case 'DECISION_GATE':
        return 80;
      case 'NOTIFYING':
        return 92;
      case 'COMPLETE':
        return 100;
      case 'FAILED':
        return 100;
      case 'OFFLINE_QUEUED':
        return 10;
      default:
        return 0;
    }
  }

  getStateLabel(state: string): string {
    const labels: Record<string, string> = {
      IDLE: 'Idle',
      LISTENING: 'Received',
      EXTRACTING: 'Extracting',
      CLARIFICATION_GATE: 'Needs Info',
      GEOCODING: 'Geo-locating',
      STORING: 'Storing',
      FOLLOW_UP_SCHEDULED: 'Follow-ups set',
      ALERTING: 'Alerting',
      DECISION_GATE: 'Awaiting Approval',
      NOTIFYING: 'Notifying',
      COMPLETE: 'Complete',
      FAILED: 'Failed',
      OFFLINE_QUEUED: 'Queued Offline',
      SYNCING: 'Syncing',
    };
    return labels[state] ?? state;
  }
}
