import { Component } from "@angular/core";
import { CommonModule } from "@angular/common";
import { FormsModule } from "@angular/forms";
import { ApiService } from "../services/api.service";

@Component({
  selector: "app-triage",
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="triage-container">
      <h2>📍 Geo Enrichment</h2>
      <p class="hint">
        Paste extracted clinical JSON and GPS coordinates to enrich with
        location data.
      </p>

      <div class="form-group">
        <label>Extracted Clinical JSON</label>
        <textarea
          [(ngModel)]="encounterJson"
          placeholder='{"syndrome": "acute_watery_diarrhea", "triage_color": "YELLOW", ...}'
          rows="6"
        ></textarea>
      </div>

      <div class="coords-row">
        <label>
          Latitude
          <input
            type="number"
            [(ngModel)]="latitude"
            step="0.0001"
            placeholder="-1.2864"
          />
        </label>
        <label>
          Longitude
          <input
            type="number"
            [(ngModel)]="longitude"
            step="0.0001"
            placeholder="36.8172"
          />
        </label>
        <button class="btn-gps" (click)="getGPS()">📍 GPS</button>
      </div>

      <button class="btn-primary" [disabled]="loading" (click)="enrich()">
        {{ loading ? "⏳ Enriching..." : "🗺️ Enrich Location" }}
      </button>

      <div class="result-card" *ngIf="result">
        <h3>Enriched Encounter</h3>
        <div
          class="admin-hierarchy"
          *ngIf="result.enriched_encounter?.admin_hierarchy as h"
        >
          <span class="hier-item">🏘️ {{ h.village }}</span>
          <span class="hier-sep">›</span>
          <span class="hier-item">{{ h.ward }} Ward</span>
          <span class="hier-sep">›</span>
          <span class="hier-item">{{ h.sub_county }}</span>
          <span class="hier-sep">›</span>
          <span class="hier-item">{{ h.county }} County</span>
        </div>

        <div
          class="facilities-list"
          *ngIf="result.enriched_encounter?.nearest_facilities?.length"
        >
          <h4>Nearest Facilities</h4>
          <div
            class="facility-card"
            *ngFor="let f of result.enriched_encounter.nearest_facilities"
          >
            <strong>{{ f.name }}</strong>
            <span class="facility-meta"
              >{{ f.distance_km }} km · {{ f.eta_minutes }} min ETA</span
            >
            <span class="facility-open" [class.open]="f.open_now">{{
              f.open_now ? "Open" : "Closed"
            }}</span>
          </div>
        </div>

        <details>
          <summary>Raw JSON</summary>
          <pre>{{ result | json }}</pre>
        </details>
      </div>

      <div class="error-msg" *ngIf="errorMsg">⚠️ {{ errorMsg }}</div>
    </div>
  `,
})
export class TriageComponent {
  encounterJson = "";
  latitude = 0;
  longitude = 0;
  result: any = null;
  loading = false;
  errorMsg = "";

  constructor(private api: ApiService) { }

  getGPS() {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition((pos) => {
      this.latitude = pos.coords.latitude;
      this.longitude = pos.coords.longitude;
    });
  }

  async enrich() {
    this.errorMsg = "";
    this.loading = true;
    let parsed: any = {};
    try {
      parsed = JSON.parse(this.encounterJson || "{}");
    } catch {
      this.errorMsg = "Invalid JSON in encounter field.";
      this.loading = false;
      return;
    }

    try {
      this.result = await this.api.enrichEncounter({
        encounter_json: parsed,
        latitude: this.latitude,
        longitude: this.longitude,
      });
    } catch (err: any) {
      this.errorMsg = `Enrichment failed: ${err.message}`;
    } finally {
      this.loading = false;
    }
  }
}
