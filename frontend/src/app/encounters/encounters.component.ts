/**
 * Encounters Component
 *
 * Shows both:
 *   1. Live in-memory sessions (from RootAgentService state machine)
 *   2. Persisted encounters from MongoDB Atlas (via GET /encounters)
 *
 * Each card has a "View Details" button that expands an inline detail
 * panel showing full clinical data, geo enrichment, vitals, and facilities.
 */

import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Observable, Subscription } from 'rxjs';
import { RootAgentService } from '../../services/root-agent.service';
import { ApiService } from '../../services/api.service';

@Component({
  selector: 'app-encounters',
  templateUrl: './encounters.component.html',
  styleUrl: './encounters.component.css',
  standalone: true,
  imports: [CommonModule, FormsModule],
})
export class EncountersComponent implements OnInit, OnDestroy {
  // ── Live sessions (in-memory state machine) ───────────────────
  liveSessions: any[] = [];
  sessionUpdates$!: Observable<any>;

  // ── Persisted encounters from MongoDB ─────────────────────────
  persistedEncounters: any[] = [];
  persistedTotal = 0;
  persistedLoading = false;
  persistedError: string | null = null;

  // ── Inline detail panel ───────────────────────────────────────
  expandedEncounterId: string | null = null;
  detailEncounter: any = null;
  detailLoading = false;
  detailError: string | null = null;

  // ── Filters ───────────────────────────────────────────────────
  filterCounty = '';
  filterSyndrome = '';
  filterTriage = '';
  filterLimit = 50;

  // ── View toggle ───────────────────────────────────────────────
  activeView: 'live' | 'persisted' = 'persisted';

  private _subs: Subscription[] = [];

  constructor(
    private rootAgent: RootAgentService,
    private api: ApiService,
  ) {}

  ngOnInit() {
    this.sessionUpdates$ = this.rootAgent.sessionUpdates$;
    this.loadLiveSessions();
    this._subs.push(
      this.sessionUpdates$.subscribe(() => this.loadLiveSessions()),
    );
    this.loadPersistedEncounters();
  }

  ngOnDestroy() {
    this._subs.forEach((s) => s.unsubscribe());
  }

  // ── Live sessions ──────────────────────────────────────────────

  loadLiveSessions() {
    this.liveSessions = this.rootAgent.getActiveSessions();
  }

  clearSession(sessionId: string) {
    this.rootAgent.clearSession(sessionId);
    this.loadLiveSessions();
  }

  // ── Persisted encounters from MongoDB ─────────────────────────

  async loadPersistedEncounters() {
    this.persistedLoading = true;
    this.persistedError = null;
    try {
      const params: string[] = [];
      if (this.filterCounty)
        params.push(`county=${encodeURIComponent(this.filterCounty)}`);
      if (this.filterSyndrome)
        params.push(`syndrome=${encodeURIComponent(this.filterSyndrome)}`);
      if (this.filterTriage)
        params.push(`triage=${encodeURIComponent(this.filterTriage)}`);
      params.push(`limit=${this.filterLimit}`);

      const qs = params.length ? '?' + params.join('&') : '';
      const res: any = await this.api.get(`/encounters${qs}`);
      this.persistedEncounters = res.encounters ?? [];
      this.persistedTotal = res.count ?? 0;
    } catch (err) {
      this.persistedError =
        err instanceof Error ? err.message : 'Failed to load encounters';
    } finally {
      this.persistedLoading = false;
    }
  }

  applyFilters() {
    this.expandedEncounterId = null;
    this.detailEncounter = null;
    this.loadPersistedEncounters();
  }

  clearFilters() {
    this.filterCounty = '';
    this.filterSyndrome = '';
    this.filterTriage = '';
    this.expandedEncounterId = null;
    this.detailEncounter = null;
    this.loadPersistedEncounters();
  }

  // ── View Details toggle ────────────────────────────────────────

  async toggleDetail(enc: any) {
    const id = enc.encounter_id;
    // Collapse if already open
    if (this.expandedEncounterId === id) {
      this.expandedEncounterId = null;
      this.detailEncounter = null;
      this.detailError = null;
      return;
    }

    this.expandedEncounterId = id;
    this.detailEncounter = null;
    this.detailError = null;
    this.detailLoading = true;

    try {
      // Try fetching full detail — falls back to the list card data on error
      const detail: any = await this.api.get(
        `/encounters/${encodeURIComponent(id)}`,
      );
      this.detailEncounter = detail;
    } catch {
      // Backend may not have the individual route yet — show what we have
      this.detailEncounter = enc;
      this.detailError = null; // silent fallback — show the card data
    } finally {
      this.detailLoading = false;
    }
  }

  isExpanded(enc: any): boolean {
    return this.expandedEncounterId === enc.encounter_id;
  }

  // ── Helpers ───────────────────────────────────────────────────

  getStateColor(state: string): string {
    switch (state) {
      case 'COMPLETE':
        return '#4caf50';
      case 'FAILED':
        return '#f44336';
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

  triageColor(t: string): string {
    switch (t) {
      case 'RED':
        return '#d32f2f';
      case 'YELLOW':
        return '#f57c00';
      case 'GREEN':
        return '#388e3c';
      default:
        return '#757575';
    }
  }

  formatSyndrome(s: string): string {
    return (s || '').replace(/_/g, ' ');
  }

  facilityEta(mins: number): string {
    if (!mins) return '—';
    return mins < 60 ? `${mins} min` : `${(mins / 60).toFixed(1)} hr`;
  }

  vitalsText(vitals: any): string {
    if (!vitals) return '—';
    const parts: string[] = [];
    if (vitals.temperature) parts.push(`Temp ${vitals.temperature}°C`);
    if (vitals.blood_pressure) parts.push(`BP ${vitals.blood_pressure}`);
    if (vitals.pulse) parts.push(`Pulse ${vitals.pulse}`);
    if (vitals.spo2) parts.push(`SpO₂ ${vitals.spo2}%`);
    if (vitals.respiratory_rate) parts.push(`RR ${vitals.respiratory_rate}`);
    return parts.length ? parts.join(' · ') : '—';
  }
}
