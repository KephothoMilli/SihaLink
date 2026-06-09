/**
 * Contact Tracing Agent UI Component
 *
 * Three views:
 *   1. Active Traces    — list all live traces with status histograms
 *   2. Initiate Trace   — start a trace by encounter_id or alert_id
 *   3. Trace Detail     — full contact list + analytics for a single trace
 */

import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatTabsModule } from '@angular/material/tabs';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatChipsModule } from '@angular/material/chips';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatDividerModule } from '@angular/material/divider';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import {
  ContactTracingAgentService,
  ContactTrace,
  ContactRecord,
} from '../../../services/agents/contact-tracing-agent.service';

const KENYA_COUNTIES = [
  'Baringo',
  'Bomet',
  'Bungoma',
  'Busia',
  'Elgeyo Marakwet',
  'Embu',
  'Garissa',
  'Homa Bay',
  'Isiolo',
  'Kajiado',
  'Kakamega',
  'Kericho',
  'Kiambu',
  'Kilifi',
  'Kirinyaga',
  'Kisii',
  'Kisumu',
  'Kitui',
  'Kwale',
  'Laikipia',
  'Lamu',
  'Machakos',
  'Makueni',
  'Mandera',
  'Marsabit',
  'Meru',
  'Migori',
  'Mombasa',
  "Murang'a",
  'Nairobi',
  'Nakuru',
  'Nandi',
  'Narok',
  'Nyamira',
  'Nyandarua',
  'Nyeri',
  'Samburu',
  'Siaya',
  'Taita Taveta',
  'Tana River',
  'Tharaka Nithi',
  'Trans Nzoia',
  'Turkana',
  'Uasin Gishu',
  'Vihiga',
  'Wajir',
  'West Pokot',
];

const WHO_SYNDROMES = [
  'acute_watery_diarrhea',
  'cholera',
  'measles',
  'acute_febrile_illness',
  'acute_respiratory_infection',
  'meningitis',
  'viral_hemorrhagic_fever',
  'malnutrition_severe',
  'acute_rash_with_fever',
];

@Component({
  selector: 'app-contact-tracing-agent',
  templateUrl: './contact-tracing-agent.component.html',
  styleUrl: './contact-tracing-agent.component.scss',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatTabsModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatChipsModule,
    MatProgressBarModule,
    MatProgressSpinnerModule,
    MatTooltipModule,
    MatDividerModule,
    MatSnackBarModule,
  ],
})
export class ContactTracingAgentComponent implements OnInit {
  readonly counties = KENYA_COUNTIES;
  readonly syndromes = WHO_SYNDROMES;
  readonly tierColors: Record<string, string> = {
    HOUSEHOLD: '#d32f2f',
    COMMUNITY: '#f57c00',
    FACILITY: '#0288d1',
    UNKNOWN: '#757575',
  };
  readonly statusColors: Record<string, string> = {
    identified: '#9e9e9e',
    contacted: '#0288d1',
    assessed: '#7b1fa2',
    cleared: '#388e3c',
    confirmed: '#d32f2f',
  };

  // ── Active Traces tab ─────────────────────────────────────────────────────
  activeTraces: ContactTrace[] = [];
  filterCounty = '';
  filterSyndrome = '';
  tracesLoading = false;

  // Inline detail on Active Traces tab (avoids tab switch)
  inlineTraceId: string | null = null;
  inlineTrace: ContactTrace | null = null;
  inlineLoading = false;

  // ── Initiate Trace tab ────────────────────────────────────────────────────
  initEncounterId = '';
  initAlertId = '';
  initiating = false;
  initResult: ContactTrace | null = null;

  // ── Trace Detail tab ──────────────────────────────────────────────────────
  detailTraceId = '';
  traceDetail: ContactTrace | null = null;
  detailLoading = false;

  // ── Update contact ────────────────────────────────────────────────────────
  selectedContact: ContactRecord | null = null;
  updateStatus: string = 'contacted';
  updateNotes = '';
  updateLoading = false;

  error: string | null = null;

  // expose for template overdue check
  readonly currentDate = new Date().toISOString();

  constructor(
    private ctService: ContactTracingAgentService,
    private snackBar: MatSnackBar,
  ) {}

  ngOnInit() {
    this.loadActiveTraces();
  }

  // ── Active traces ─────────────────────────────────────────────────────────

  async loadActiveTraces() {
    this.tracesLoading = true;
    this.error = null;
    try {
      const res = await this.ctService.getActiveTraces({
        county: this.filterCounty || undefined,
        syndrome: this.filterSyndrome || undefined,
        limit: 50,
      });
      this.activeTraces = res.traces ?? [];
    } catch (err) {
      this.error = err instanceof Error ? err.message : 'Failed to load traces';
    } finally {
      this.tracesLoading = false;
    }
  }

  /** Toggle inline detail panel on the Active Traces tab card. */
  async openInlineDetail(traceId: string) {
    // Collapse if already open
    if (this.inlineTraceId === traceId) {
      this.inlineTraceId = null;
      this.inlineTrace = null;
      return;
    }
    this.inlineTraceId = traceId;
    this.inlineTrace = null;
    this.inlineLoading = true;
    try {
      this.inlineTrace = await this.ctService.getTraceStatus(traceId);
    } catch (err) {
      this.error =
        err instanceof Error ? err.message : 'Failed to load trace detail';
      this.inlineTraceId = null;
    } finally {
      this.inlineLoading = false;
    }
  }

  isInlineExpanded(traceId: string): boolean {
    return this.inlineTraceId === traceId;
  }

  // ── Initiate trace ────────────────────────────────────────────────────────

  async initiateTrace() {
    if (!this.initEncounterId.trim() && !this.initAlertId.trim()) {
      this.snackBar.open('Enter an Encounter ID or Alert ID', 'Dismiss', {
        duration: 4000,
      });
      return;
    }
    this.initiating = true;
    this.initResult = null;
    this.error = null;
    try {
      this.initResult = await this.ctService.initiateTrace({
        encounter_id: this.initEncounterId.trim() || undefined,
        alert_id: this.initAlertId.trim() || undefined,
        initiated_by: 'dashboard',
      });
      this.snackBar.open(
        `Trace ${this.initResult.trace_id} — ${this.initResult.total_contacts ?? 0} contacts identified`,
        'OK',
        { duration: 5000 },
      );
      this.loadActiveTraces();
    } catch (err) {
      this.error =
        err instanceof Error ? err.message : 'Failed to initiate trace';
    } finally {
      this.initiating = false;
    }
  }

  // ── Trace detail ──────────────────────────────────────────────────────────

  async loadTraceDetail(traceId?: string) {
    const id = traceId ?? this.detailTraceId.trim();
    if (!id) {
      this.snackBar.open('Enter a Trace ID', 'Dismiss', { duration: 4000 });
      return;
    }
    this.detailLoading = true;
    this.traceDetail = null;
    this.selectedContact = null;
    this.error = null;
    try {
      this.traceDetail = await this.ctService.getTraceStatus(id);
      this.detailTraceId = id;
    } catch (err) {
      this.error = err instanceof Error ? err.message : 'Trace not found';
    } finally {
      this.detailLoading = false;
    }
  }

  openContactUpdate(contact: ContactRecord) {
    this.selectedContact = contact;
    this.updateStatus = 'contacted';
    this.updateNotes = '';
  }

  async submitContactUpdate() {
    if (!this.selectedContact || !this.traceDetail) return;
    this.updateLoading = true;
    try {
      await this.ctService.updateContactStatus({
        trace_id: this.traceDetail.trace_id,
        contact_id: this.selectedContact.contact_id,
        status: this.updateStatus as any,
        notes: this.updateNotes,
      });
      this.snackBar.open('Contact status updated', 'OK', { duration: 3000 });
      this.selectedContact = null;
      await this.loadTraceDetail(this.traceDetail.trace_id);
    } catch (err) {
      this.error = err instanceof Error ? err.message : 'Update failed';
    } finally {
      this.updateLoading = false;
    }
  }

  async resolveTrace(traceId: string) {
    try {
      await this.ctService.resolveTrace(traceId, 'Resolved via dashboard');
      this.snackBar.open(`Trace ${traceId} resolved`, 'OK', { duration: 3000 });
      this.traceDetail = null;
      this.loadActiveTraces();
    } catch (err) {
      this.error =
        err instanceof Error ? err.message : 'Failed to resolve trace';
    }
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  tierColor(tier: string) {
    return this.tierColors[tier] ?? '#757575';
  }
  statusColor(s: string) {
    return this.statusColors[s] ?? '#757575';
  }
  completionPct(t: ContactTrace) {
    return (
      t.analytics?.completion_rate_pct ??
      (t.total_contacts > 0
        ? Math.round((t.contacted_count / t.total_contacts) * 100)
        : 0)
    );
  }
  histogramKeys(obj: Record<string, number> | undefined): string[] {
    return obj ? Object.keys(obj) : [];
  }
  formatSyndrome(s: string) {
    return s.replace(/_/g, ' ');
  }
  escalationColor(level?: string) {
    if (level === 'NATIONAL') return '#d32f2f';
    if (level === 'REGIONAL') return '#f57c00';
    return '#0288d1';
  }
}
