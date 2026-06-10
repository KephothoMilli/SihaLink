/**
 * Contact Tracing Agent UI Component
 *
 * Tab 1 — Active Traces: MatTable + MatPaginator (server-side)
 * Tab 2 — Initiate Trace: manual trace start
 * Tab 3 — Trace Detail: analytics + MatTable contact list with update panel
 */

import {
  Component,
  OnInit,
  ViewChild,
  AfterViewInit,
  ChangeDetectorRef,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

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
import { MatTableModule, MatTableDataSource } from '@angular/material/table';
import {
  MatPaginatorModule,
  MatPaginator,
  PageEvent,
} from '@angular/material/paginator';
import { MatSortModule, MatSort } from '@angular/material/sort';
import { MatBadgeModule } from '@angular/material/badge';

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
    MatTableModule,
    MatPaginatorModule,
    MatSortModule,
    MatBadgeModule,
  ],
})
export class ContactTracingAgentComponent implements OnInit, AfterViewInit {
  @ViewChild('tracesPaginator') tracesPaginator!: MatPaginator;
  @ViewChild('tracesSort') tracesSort!: MatSort;
  @ViewChild('contactsPaginator') contactsPaginator!: MatPaginator;

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

  // ── Tab 1: Active Traces table ────────────────────────────────────────────
  tracesDataSource = new MatTableDataSource<ContactTrace>([]);
  tracesColumns = [
    'trace_id',
    'syndrome',
    'location',
    'progress',
    'contacts',
    'escalation',
    'actions',
  ];
  tracesTotal = 0;
  tracesLoading = false;
  filterCounty = '';
  filterSyndrome = '';
  pageSize = 10;
  pageIndex = 0;
  readonly pageSizeOptions = [10, 20, 50];

  // Inline detail on Active Traces table row
  expandedTrace: ContactTrace | null = null;
  inlineTrace: ContactTrace | null = null;
  inlineLoading = false;

  // ── Tab 2: Initiate Trace ─────────────────────────────────────────────────
  initEncounterId = '';
  initAlertId = '';
  initiating = false;
  initResult: ContactTrace | null = null;

  // ── Tab 3: Trace Detail ───────────────────────────────────────────────────
  detailTraceId = '';
  traceDetail: ContactTrace | null = null;
  detailLoading = false;

  // Contacts table inside Trace Detail
  contactsDataSource = new MatTableDataSource<ContactRecord>([]);
  contactsColumns = [
    'contact_id',
    'risk_tier',
    'location',
    'status',
    'due_date',
    'action',
  ];

  selectedContact: ContactRecord | null = null;
  updateStatus = 'contacted';
  updateNotes = '';
  updateLoading = false;

  error: string | null = null;
  readonly currentDate = new Date().toISOString();

  constructor(
    private ctService: ContactTracingAgentService,
    private snackBar: MatSnackBar,
    private router: Router,
    private cd: ChangeDetectorRef,
  ) {}

  ngOnInit() {
    this.loadActiveTraces();
  }

  ngAfterViewInit() {
    this.tracesDataSource.sort = this.tracesSort;
    this.contactsDataSource.paginator = this.contactsPaginator;
  }

  // ── Active Traces ─────────────────────────────────────────────────────────

  async loadActiveTraces() {
    this.tracesLoading = true;
    this.error = null;
    try {
      const res = await this.ctService.getActiveTraces({
        county: this.filterCounty || undefined,
        syndrome: this.filterSyndrome || undefined,
        limit: 200, // load all then paginate client-side
      });
      const all = res.traces ?? [];
      this.tracesTotal = all.length;
      // Use MatTableDataSource built-in pagination and sorting
      this.tracesDataSource.data = all;
      this.tracesDataSource.paginator = this.tracesPaginator;
      this.tracesDataSource.sort = this.tracesSort;
    } catch (err) {
      this.error = err instanceof Error ? err.message : 'Failed to load traces';
    } finally {
      this.tracesLoading = false;
    }
  }

  onTracesPage(e: PageEvent) {
    this.pageSize = e.pageSize;
    this.pageIndex = e.pageIndex;
  }

  applyFilters() {
    this.pageIndex = 0;
    this.expandedTrace = null;
    if (this.tracesDataSource.paginator) {
      this.tracesDataSource.paginator.pageIndex = 0;
    }
    this.loadActiveTraces();
  }

  // ── Row expand ────────────────────────────────────────────────────────────

  async toggleRow(trace: ContactTrace) {
    if (this.expandedTrace === trace) {
      this.expandedTrace = null;
      this.inlineTrace = null;
      return;
    }
    this.expandedTrace = trace;
    this.inlineTrace = null;
    this.inlineLoading = true;
    try {
      this.inlineTrace = await this.ctService.getTraceStatus(trace.trace_id);
    } catch {
      this.inlineTrace = trace;
    } finally {
      this.inlineLoading = false;
    }
  }

  isExpanded(trace: ContactTrace) {
    return this.expandedTrace === trace;
  }

  // ── Initiate Trace ────────────────────────────────────────────────────────

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
        `Trace ${this.initResult.trace_id} — ${this.initResult.total_contacts ?? 0} contacts`,
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

  // ── Trace Detail ──────────────────────────────────────────────────────────

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
      this.contactsDataSource.data = this.traceDetail.contacts ?? [];
    } catch (err) {
      this.error = err instanceof Error ? err.message : 'Trace not found';
    } finally {
      this.detailLoading = false;
    }
  }

  openContactUpdate(c: ContactRecord) {
    this.selectedContact = c;
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

  tierColor(t: string) {
    return this.tierColors[t] ?? '#757575';
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
  histogramKeys(o?: Record<string, number>) {
    return o ? Object.keys(o) : [];
  }
  formatSyndrome(s: string) {
    return s.replace(/_/g, ' ');
  }
  escalationColor(l?: string) {
    if (l === 'NATIONAL') return '#d32f2f';
    if (l === 'REGIONAL') return '#f57c00';
    return '#0288d1';
  }

  goToEncounters() {
    this.router.navigate(['/encounters']);
  }
}
