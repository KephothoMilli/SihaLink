/**
 * Encounters Component
 *
 * View and manage all encounters
 */

import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Observable } from 'rxjs';
import { RootAgentService } from '../../services/root-agent.service';

@Component({
  selector: 'app-encounters',
  templateUrl: './encounters.component.html',
  styleUrl: './encounters.component.css',
  standalone: true,
  imports: [CommonModule],
})
export class EncountersComponent implements OnInit {
  encounters: any[] = [];
  sessionUpdates$!: Observable<any>;

  constructor(private rootAgent: RootAgentService) {}

  ngOnInit() {
    this.sessionUpdates$ = this.rootAgent.sessionUpdates$;
    this.loadEncounters();
    this.sessionUpdates$.subscribe(() => {
      this.loadEncounters();
    });
  }

  loadEncounters() {
    this.encounters = this.rootAgent.getActiveSessions();
  }

  getStateColor(state: string): string {
    switch (state) {
      case 'COMPLETE':
        return '#4caf50';
      case 'IDLE':
        return '#9e9e9e';
      case 'DECISION_GATE':
        return '#ff9800';
      case 'EXTRACTING':
      case 'GEOCODING':
      case 'STORING':
      case 'NOTIFYING':
        return '#2196f3';
      default:
        return '#757575';
    }
  }

  clearSession(sessionId: string) {
    this.rootAgent.clearSession(sessionId);
    this.loadEncounters();
  }
}
