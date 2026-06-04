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
      case 'ERROR':
        return 'var(--color-red)';
      case 'DECISION_GATE':
        return 'var(--color-yellow)';
      default:
        return 'var(--color-secondary)';
    }
  }

  getStateProgress(state: string): number {
    switch (state) {
      case 'IDLE': return 10;
      case 'LISTENING': return 25;
      case 'EXTRACTING': return 40;
      case 'GEOCODING': return 55;
      case 'STORING': return 70;
      case 'DECISION_GATE': return 80;
      case 'NOTIFYING': return 90;
      case 'COMPLETE': return 100;
      default: return 0;
    }
  }
}
