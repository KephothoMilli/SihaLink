/**
 * Encounters Component — Material Table with server-side pagination
 *
 * Uses MatTable + MatPaginator backed by GET /encounters.
 * All records (seeded or live) are treated as real clinical encounter data.
 * Expandable detail row shows full clinical, vitals, geo, and facilities data.
 */

import {
  Component,
  OnInit,
  OnDestroy,
  ViewChild,
  AfterViewInit,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subscription } from 'rxjs';

// Angular Material
import { MatTableModule, MatTableDataSource } from '@angular/material/table';
import {
  MatPaginatorModule,
  MatPaginator,
  PageEvent,
} from '@angular/material/paginator';
import { MatSortModule, MatSort } from '@angular/material/sort';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatCardModule } from '@angular/material/card';
import { MatBadgeModule } from '@angular/material/badge';

import { RootAgentService } from '../../services/root-agent.service';
import { ApiService } from '../../services/api.service';

@Component({
  selector: 'app-encounters',
  templateUrl: './encounters.component.html',
  styleUrl: './encounters.component.css',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatTableModule,
    MatPaginatorModule,
    MatSortModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    MatIconModule,
    MatChipsModule,
    MatProgressBarModule,
    MatTooltipModule,
    MatCardModule,
    MatBadgeModule,
  ],
})
export class EncountersComponent implements OnInit, AfterViewInit, OnDestroy {
  @ViewChild(MatPaginator) paginator!: MatPaginator;
  @ViewChild(MatSort) sort!: MatSort;

  // ── Filter dropdowns ──────────────────────────────────────────
  readonly KENYA_COUNTIES = [
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
  readonly WHO_SYNDROMES = [
    'acute_watery_diarrhea',
    'acute_bloody_diarrhea',
    'acute_febrile_illness',
    'acute_respiratory_infection',
    'acute_rash_with_fever',
    'malnutrition_severe',
    'neonatal_tetanus',
    'meningitis',
    'viral_hemorrhagic_fever',
    'cholera',
    'measles',
    'pneumonia',
    'typhoid',
    'unknown',
  ];

  // ── Table ─────────────────────────────────────────────────────
  dataSource = new MatTableDataSource<any>([]);
  displayedColumns = [
    'triage',
    'syndrome',
    'complaint',
    'location',
    'patient',
    'chw',
    'timestamp',
    'expand',
  ];
  totalRecords = 0;
  loading = false;
  error: string | null = null;

  // ── Pagination ────────────────────────────────────────────────
  pageSize = 20;
  pageIndex = 0;
  readonly pageSizeOptions = [10, 20, 50, 100];

  // ── Filters ───────────────────────────────────────────────────
  filterCounty = '';
  filterSyndrome = '';
  filterTriage = '';

  // ── Expandable row ────────────────────────────────────────────
  expandedRow: any = null;
  detailEncounter: any = null;
  detailLoading = false;

  // ── Live sessions tab ─────────────────────────────────────────
  liveSessions: any[] = [];
  activeTab = 0;

  private _subs: Subscription[] = [];

  constructor(
    private rootAgent: RootAgentService,
    private api: ApiService,
  ) {}

  ngOnInit() {
    this.loadLiveSessions();
    this._subs.push(
      this.rootAgent.sessionUpdates$.subscribe(() => this.loadLiveSessions()),
    );
    this.loadEncounters();
  }

  ngAfterViewInit() {
    this._subs.push(
      this.sort.sortChange.subscribe(() => {
        this.pageIndex = 0;
        this.loadEncounters();
      }),
    );
  }

  ngOnDestroy() {
    this._subs.forEach((s) => s.unsubscribe());
  }

  // ── Live sessions ──────────────────────────────────────────────

  loadLiveSessions() {
    this.liveSessions = this.rootAgent.getActiveSessions();
  }

  clearSession(id: string) {
    this.rootAgent.clearSession(id);
    this.loadLiveSessions();
  }

  // ── Server-side load ───────────────────────────────────────────

  async loadEncounters() {
    this.loading = true;
    this.error = null;
    try {
      const params: string[] = [];
      if (this.filterCounty)
        params.push(`county=${encodeURIComponent(this.filterCounty)}`);
      if (this.filterSyndrome)
        params.push(`syndrome=${encodeURIComponent(this.filterSyndrome)}`);
      if (this.filterTriage)
        params.push(`triage=${encodeURIComponent(this.filterTriage)}`);
      params.push(`limit=${this.pageSize}`);
      params.push(`skip=${this.pageIndex * this.pageSize}`);

      const qs = params.length ? '?' + params.join('&') : '';
      const res: any = await this.api.get(`/api/encounters${qs}`);
      this.dataSource.data = res.encounters ?? [];
      this.totalRecords = res.count ?? 0;
    } catch (err) {
      this.error =
        err instanceof Error ? err.message : 'Could not reach the backend';
      this.dataSource.data = [];
      this.totalRecords = 0;
    } finally {
      this.loading = false;
    }
  }

  onPageChange(e: PageEvent) {
    this.pageSize = e.pageSize;
    this.pageIndex = e.pageIndex;
    this.expandedRow = null;
    this.loadEncounters();
  }

  applyFilters() {
    this.pageIndex = 0;
    this.expandedRow = null;
    if (this.paginator) {
      this.paginator.pageIndex = 0;
    }
    this.loadEncounters();
  }

  clearFilters() {
    this.filterCounty = this.filterSyndrome = this.filterTriage = '';
    this.pageIndex = 0;
    this.expandedRow = null;
    if (this.paginator) {
      this.paginator.pageIndex = 0;
    }
    this.loadEncounters();
  }

  // ── Row expansion ──────────────────────────────────────────────

  async toggleRow(row: any) {
    if (this.expandedRow === row) {
      this.expandedRow = null;
      this.detailEncounter = null;
      return;
    }
    this.expandedRow = row;
    this.detailEncounter = null;
    this.detailLoading = true;
    try {
      this.detailEncounter = await this.api.get(
        `/api/encounters/${encodeURIComponent(row.encounter_id)}`,
      );
    } catch {
      this.detailEncounter = row;
    } finally {
      this.detailLoading = false;
    }
  }

  isExpanded(row: any) {
    return this.expandedRow === row;
  }

  // ── Helpers ───────────────────────────────────────────────────

  triageColor(t?: string) {
    switch (t) {
      case 'RED':
        return '#d32f2f';
      case 'YELLOW':
        return '#f57c00';
      case 'GREEN':
        return '#388e3c';
      default:
        return '#9e9e9e';
    }
  }
  triageBg(t?: string) {
    return this.triageColor(t) + '18';
  }

  /** Returns vitals regardless of whether stored as 'vitals' or 'vital_signs' */
  getVitals(enc: any): any {
    return enc?.extracted?.vitals ?? enc?.extracted?.vital_signs ?? null;
  }

  getStateColor(s: string) {
    switch (s) {
      case 'COMPLETE':
        return '#388e3c';
      case 'FAILED':
        return '#d32f2f';
      case 'DECISION_GATE':
        return '#f57c00';
      default:
        return '#1976d2';
    }
  }

  formatSyndrome(s?: string) {
    return (s || '').replace(/_/g, ' ');
  }
  facilityEta(m: number) {
    return !m ? '—' : m < 60 ? `${m} min` : `${(m / 60).toFixed(1)} hr`;
  }
}
