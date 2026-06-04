/**
 * Root App Component — SihaLink (Standalone, Angular 17+)
 * Central shell with routing, online/offline handling, and agent health polling.
 */

import { Component, OnInit, OnDestroy } from '@angular/core';
import { RouterModule, Router } from '@angular/router';
import { CommonModule } from '@angular/common';
import { Observable } from 'rxjs';
import { RootAgentService } from '../services/root-agent.service';
import { ApiService } from '../services/api.service';
import { OfflineSyncService } from '../services/offline-sync.service';

export interface AppToast {
  id: number;
  message: string;
  type: 'info' | 'success' | 'warning' | 'error';
  icon: string;
}

@Component({
  selector: 'app-root',
  templateUrl: './app.component.html',
  styleUrl: './app.component.css',
  standalone: true,
  imports: [CommonModule, RouterModule],
})
export class AppComponent implements OnInit, OnDestroy {
  title = 'SihaLink - Multi-Agent System';
  isMenuOpen = false;

  // Initialised in ngOnInit to avoid "used before initialization" TS error
  agentStatus$!: Observable<any>;

  isOnline = navigator.onLine;
  offlineQueueSize = 0;
  gateSession: any = null;

  // Toast notification queue
  toasts: AppToast[] = [];
  private toastCounter = 0;
  private lastAgentStatus: any = null;

  private onlineHandler = () => {
    this.isOnline = true;
    this.syncOfflineQueue();
  };

  private offlineHandler = () => {
    this.isOnline = false;
  };

  private healthInterval?: ReturnType<typeof setInterval>;

  constructor(
    private rootAgent: RootAgentService,
    private router: Router,
    private api: ApiService,
    private syncService: OfflineSyncService,
  ) {}

  ngOnInit() {
    // Safe to access rootAgent here — constructor has already run
    this.agentStatus$ = this.rootAgent.agentStatus$;

    window.addEventListener('online', this.onlineHandler);
    window.addEventListener('offline', this.offlineHandler);
    this.offlineQueueSize = this.syncService.getQueueSize();

    this.rootAgent.checkAgentHealth();
    this.healthInterval = setInterval(
      () => this.rootAgent.checkAgentHealth(),
      30_000,
    );

    // Agent health toast notifications
    this.agentStatus$.subscribe((status) => {
      if (!status || !this.lastAgentStatus) {
        this.lastAgentStatus = status;
        return;
      }
      const agents = ['intake', 'geo', 'data', 'notify', 'surveillance'];
      const labels: Record<string, string> = {
        intake: '🎤 Intake', geo: '📍 Geo', data: '💾 Data',
        notify: '📨 Notify', surveillance: '📊 Surveillance',
      };
      for (const agent of agents) {
        const wasHealthy = this.lastAgentStatus[agent];
        const isHealthy = status[agent];
        if (!wasHealthy && isHealthy) {
          this.showToast(`${labels[agent]} Agent is now online`, 'success', '✅');
        } else if (wasHealthy && !isHealthy) {
          this.showToast(`${labels[agent]} Agent went offline`, 'warning', '⚠️');
        }
      }
      this.lastAgentStatus = status;
    });

    this.rootAgent.sessionUpdates$.subscribe((session) => {
      if (session?.state === 'DECISION_GATE') {
        this.gateSession = session;
        this.showToast('Clinical Gate requires your approval', 'warning', '🔔');
      } else if (
        this.gateSession &&
        session &&
        this.gateSession.sessionId === session.sessionId
      ) {
        this.gateSession = null;
      }
    });

    if (this.isOnline && this.offlineQueueSize > 0) {
      this.syncOfflineQueue();
    }
  }

  showToast(message: string, type: AppToast['type'] = 'info', icon = 'ℹ️') {
    const id = ++this.toastCounter;
    this.toasts.push({ id, message, type, icon });
    setTimeout(() => this.dismissToast(id), 4000);
  }

  dismissToast(id: number) {
    this.toasts = this.toasts.filter((t) => t.id !== id);
  }

  async confirmGate(confirmed: boolean) {
    if (!this.gateSession) return;
    try {
      await this.rootAgent.confirmEncounterDecision(
        this.gateSession.sessionId,
        confirmed,
      );
      this.gateSession = null;
    } catch (error) {
      console.error('Failed to confirm decision gate:', error);
    }
  }

  ngOnDestroy() {
    window.removeEventListener('online', this.onlineHandler);
    window.removeEventListener('offline', this.offlineHandler);
    if (this.healthInterval) clearInterval(this.healthInterval);
  }

  toggleMenu() {
    this.isMenuOpen = !this.isMenuOpen;
  }

  navigateTo(path: string) {
    this.router.navigate([path]);
    this.isMenuOpen = false;
  }

  private async syncOfflineQueue() {
    try {
      const queue = this.syncService.getQueue();
      for (const encounter of queue) {
        try {
          await this.rootAgent.startEncounter(encounter);
          this.syncService.removeFromQueue(encounter);
        } catch (error) {
          console.error('Failed to sync encounter:', error);
        }
      }
      this.offlineQueueSize = this.syncService.getQueueSize();
    } catch (error) {
      console.error('Offline sync failed:', error);
    }
  }
}
