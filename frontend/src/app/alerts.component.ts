import { Component, EventEmitter, OnInit, Output } from "@angular/core";
import { CommonModule } from "@angular/common";
import { FormsModule } from "@angular/forms";
import { ApiService } from "../services/api.service";

interface Alert {
  _id?: string;
  alert_id?: string;
  encounter_id?: string;
  syndrome: string;
  triage_color?: string;
  status: string;
  location?: { county: string; ward: string };
  summary?: string;
  timestamp?: string;
  percent_above_baseline?: number;
  count?: number;
}

@Component({
  selector: "app-alerts",
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="alerts-container">
      <div class="alerts-header">
        <h2>⚠️ Active Alerts</h2>
        <div class="filter-row">
          <input
            type="text"
            [(ngModel)]="countyFilter"
            placeholder="Filter by county..."
            (ngModelChange)="load()"
          />
          <button class="btn-primary" [disabled]="loading" (click)="load()">
            {{ loading ? "⏳" : "🔄 Refresh" }}
          </button>
        </div>
      </div>

      <div class="alerts-empty" *ngIf="!loading && alerts.length === 0">
        ✅ No active alerts{{ countyFilter ? " for " + countyFilter : "" }}.
      </div>

      <div class="alert-card" *ngFor="let a of alerts" [class]="alertClass(a)">
        <div class="alert-top">
          <span class="triage-badge" [class]="triageClass(a)">
            {{ a.triage_color || "ALERT" }}
          </span>
          <span class="alert-syndrome">{{ a.syndrome }}</span>
          <span class="alert-status">{{ a.status }}</span>
        </div>

        <div class="alert-location" *ngIf="a.location">
          📍 {{ a.location.ward }} Ward, {{ a.location.county }} County
        </div>

        <div class="alert-summary" *ngIf="a.summary">{{ a.summary }}</div>

        <div class="alert-meta">
          <span *ngIf="a.count">Cases: {{ a.count }}</span>
          <span *ngIf="a.percent_above_baseline">
            +{{ a.percent_above_baseline }}% above baseline
          </span>
          <span *ngIf="a.timestamp">{{ a.timestamp | date: "short" }}</span>
        </div>

        <div class="alert-actions" *ngIf="a.status === 'active'">
          <button
            class="btn-acknowledge"
            [disabled]="actionLoading === (a._id || a.alert_id)"
            (click)="acknowledge(a)"
          >
            ✅ Acknowledge
          </button>
          <button
            class="btn-resolve"
            [disabled]="actionLoading === (a._id || a.alert_id)"
            (click)="resolve(a)"
          >
            ✔️ Resolve
          </button>
        </div>
      </div>
    </div>
  `,
})
export class AlertsComponent implements OnInit {
  @Output() alertCountChange = new EventEmitter<number>();

  alerts: Alert[] = [];
  loading = false;
  actionLoading: string | null = null;
  countyFilter = "";

  constructor(private api: ApiService) { }

  ngOnInit() {
    this.load();
  }

  async load() {
    this.loading = true;
    try {
      const res = await this.api.queryActiveAlerts(
        this.countyFilter ? { county: this.countyFilter } : {},
      );
      this.alerts = res?.alerts ?? [];
      this.alertCountChange.emit(
        this.alerts.filter((a) => a.status === "active").length,
      );
    } catch (err) {
      console.error("Failed to load alerts", err);
    } finally {
      this.loading = false;
    }
  }

  async acknowledge(alert: Alert) {
    const id = alert._id || alert.alert_id || "";
    this.actionLoading = id;
    try {
      await this.api.updateAlertStatus({
        alert_id: id,
        status: "acknowledged",
      });
      alert.status = "acknowledged";
      this.alertCountChange.emit(
        this.alerts.filter((a) => a.status === "active").length,
      );
    } catch (err) {
      console.error("Acknowledge failed", err);
    } finally {
      this.actionLoading = null;
    }
  }

  async resolve(alert: Alert) {
    const id = alert._id || alert.alert_id || "";
    const notes = window.prompt("Resolution notes (optional):") ?? "";
    this.actionLoading = id;
    try {
      await this.api.resolveAlert({ alert_id: id, notes });
      alert.status = "resolved";
      this.alertCountChange.emit(
        this.alerts.filter((a) => a.status === "active").length,
      );
    } catch (err) {
      console.error("Resolve failed", err);
    } finally {
      this.actionLoading = null;
    }
  }

  alertClass(a: Alert): string {
    if (a.triage_color === "RED") return "alert-red";
    if (a.triage_color === "YELLOW") return "alert-yellow";
    return "alert-default";
  }

  triageClass(a: Alert): string {
    if (a.triage_color === "RED") return "triage-red";
    if (a.triage_color === "YELLOW") return "triage-yellow";
    return "triage-green";
  }
}
