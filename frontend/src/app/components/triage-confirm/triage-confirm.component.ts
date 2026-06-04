/**
 * TriageConfirmComponent — SihaLink Web
 * Human-in-the-loop gate: CHV confirms or declines a referral/alert.
 * Reads pending gate data from localStorage (set by AppComponent polling)
 * and POSTs the decision to the Orchestrator.
 */

import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../../services/api.service';

export interface PendingGate {
  session_id: string;
  encounter_id: string;
  triage_color: 'RED' | 'YELLOW';
  summary: string;
}

@Component({
  selector: 'app-triage-confirm',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div
      class="gate-overlay"
      *ngIf="gate"
      role="dialog"
      aria-modal="true"
      aria-labelledby="gate-title"
    >
      <div
        class="gate-modal"
        [class.red]="gate.triage_color === 'RED'"
        [class.yellow]="gate.triage_color === 'YELLOW'"
      >
        <div
          class="gate-triage-badge"
          [class.triage-red]="gate.triage_color === 'RED'"
          [class.triage-yellow]="gate.triage_color === 'YELLOW'"
        >
          {{ gate.triage_color }}
        </div>

        <h2 id="gate-title">Confirm Referral?</h2>
        <p class="gate-summary">{{ gate.summary }}</p>
        <p class="gate-encounter">
          Encounter: <code>{{ gate.encounter_id }}</code>
        </p>

        <div class="gate-actions">
          <button
            class="btn-confirm"
            [disabled]="isSubmitting"
            (click)="onDecision(true)"
          >
            ✅ Confirm &amp; Send
          </button>
          <button
            class="btn-decline"
            [disabled]="isSubmitting"
            (click)="onDecision(false)"
          >
            ❌ Decline
          </button>
        </div>

        <div class="gate-result" *ngIf="resultMessage" aria-live="polite">
          {{ resultMessage }}
        </div>
      </div>
    </div>
  `,
})
export class TriageConfirmComponent implements OnInit {
  /** Pass the gate data in from the parent (AppComponent) */
  @Input() gate: PendingGate | null = null;

  /** Emits true/false once the CHV makes a decision */
  @Output() decision = new EventEmitter<boolean>();

  isSubmitting = false;
  resultMessage = '';

  constructor(private api: ApiService) {}

  ngOnInit() {
    // If no gate was passed via @Input, try loading from localStorage
    if (!this.gate) {
      this.gate = this.loadFromStorage();
    }
  }

  async onDecision(confirmed: boolean) {
    if (!this.gate || this.isSubmitting) return;

    this.isSubmitting = true;
    const { session_id } = this.gate;

    try {
      await this.api.confirmEncounter(session_id, confirmed);
      this.resultMessage = confirmed
        ? '✅ Referral confirmed. Facility notified via Telegram.'
        : '❌ Referral declined. Encounter logged.';
      this.clearStorage();
      // Emit decision so parent can clear the gate
      setTimeout(() => {
        this.decision.emit(confirmed);
        this.gate = null;
        this.resultMessage = '';
      }, 1500);
    } catch (err: any) {
      this.resultMessage = `Error: ${err.message}`;
    } finally {
      this.isSubmitting = false;
    }
  }

  private loadFromStorage(): PendingGate | null {
    try {
      const raw = localStorage.getItem('afya_pending_gate');
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  }

  private clearStorage() {
    localStorage.removeItem('afya_pending_gate');
  }
}
