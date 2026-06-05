import {
  Component,
  EventEmitter,
  OnDestroy,
  OnInit,
  Output,
} from "@angular/core";
import { CommonModule } from "@angular/common";
import { FormsModule } from "@angular/forms";
import { ApiService } from "../services/api.service";
import { OfflineSyncService } from "../services/offline-sync.service";

type RecordingState = "idle" | "recording" | "processing" | "done" | "error";

type LifecycleState =
  | "IDLE"
  | "LISTENING"
  | "EXTRACTING"
  | "CLARIFICATION_GATE"
  | "GEOCODING"
  | "STORING"
  | "FOLLOW_UP_SCHEDULED"
  | "ALERTING"
  | "DECISION_GATE"
  | "NOTIFYING"
  | "COMPLETE"
  | "FAILED"
  | "OFFLINE_QUEUED"
  | "SYNCING";

interface LifecycleStep {
  state: LifecycleState;
  label: string;
  icon: string;
  description: string;
}

const LIFECYCLE_STEPS: LifecycleStep[] = [
  { state: "LISTENING",   label: "Received",     icon: "🎙️", description: "Audio / text received by the swarm" },
  { state: "EXTRACTING",  label: "Extracting",   icon: "🧠", description: "Gemini AI extracting clinical data" },
  { state: "GEOCODING",   label: "Geo-locating", icon: "📍", description: "Resolving GPS to admin hierarchy" },
  { state: "STORING",     label: "Storing",      icon: "💾", description: "Saving to MongoDB Atlas" },
  { state: "FOLLOW_UP_SCHEDULED", label: "Follow-ups", icon: "📅", description: "Follow-up schedule written" },
  { state: "NOTIFYING",   label: "Notifying",    icon: "📨", description: "Telegram dispatch to facility" },
  { state: "COMPLETE",    label: "Complete",     icon: "✅", description: "Encounter successfully processed" },
];

@Component({
  selector: "app-intake",
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="intake-container">
      <!-- ── Header ────────────────────────────────────── -->
      <div class="intake-header">
        <h2>🎙️ CHV Encounter Intake</h2>
        <p class="intake-hint">
          Speak in any language — Dholuo, Swahili, Kikuyu, Somali, or English.
          The AI swarm handles the rest.
        </p>
      </div>

      <!-- ── GPS Coordinates ───────────────────────────── -->
      <div class="coords-row">
        <label class="coord-label">
          <span>Latitude</span>
          <input type="number" [(ngModel)]="latitude" step="0.0001" placeholder="-1.2864" id="lat-input"/>
        </label>
        <label class="coord-label">
          <span>Longitude</span>
          <input type="number" [(ngModel)]="longitude" step="0.0001" placeholder="36.8172" id="lng-input"/>
        </label>
        <button class="btn-gps" (click)="getGPS()" title="Use device GPS" id="gps-btn">
          <span *ngIf="!gpsLoading">📍 Use GPS</span>
          <span *ngIf="gpsLoading" class="spinner-sm">⟳</span>
        </button>
      </div>

      <!-- ── Recording Controls ────────────────────────── -->
      <div class="recorder-section">
        <button
          id="record-btn"
          class="btn-record"
          [class.recording]="recordState === 'recording'"
          [class.processing]="recordState === 'processing'"
          [disabled]="recordState === 'processing' || isLifecycleRunning"
          (click)="toggleRecording()"
          [attr.aria-label]="recordState === 'recording' ? 'Stop recording' : 'Start recording'"
        >
          <span class="record-icon">
            <span *ngIf="recordState === 'idle' || recordState === 'done' || recordState === 'error'">🎙️</span>
            <span *ngIf="recordState === 'recording'" class="pulse-ring">⏹️</span>
            <span *ngIf="recordState === 'processing'" class="spin">⟳</span>
          </span>
          <span class="record-label">
            <ng-container *ngIf="recordState === 'idle'">Start Recording</ng-container>
            <ng-container *ngIf="recordState === 'recording'">Stop &amp; Submit</ng-container>
            <ng-container *ngIf="recordState === 'processing'">Uploading…</ng-container>
            <ng-container *ngIf="recordState === 'done'">Record Again</ng-container>
            <ng-container *ngIf="recordState === 'error'">Retry</ng-container>
          </span>
        </button>

        <div class="recording-wave" *ngIf="recordState === 'recording'">
          <span class="wave-bar" *ngFor="let b of waveBars" [style.height.px]="b"></span>
        </div>

        <div class="record-timer" *ngIf="recordState === 'recording'">
          {{ recordSeconds | number:'1.0-0' }}s
        </div>
      </div>

      <!-- ── Text Report Fallback ───────────────────────── -->
      <div class="text-report-section">
        <div class="or-divider"><span>or type report</span></div>
        <div class="text-input-row">
          <textarea
            id="text-report-input"
            [(ngModel)]="textReport"
            placeholder="Describe symptoms in any language… e.g. 'Mtoto miaka 2, homa kali, kuhara maji'"
            rows="3"
            [disabled]="isLifecycleRunning"
          ></textarea>
          <button
            id="text-submit-btn"
            class="btn-text-submit"
            (click)="submitTextReport()"
            [disabled]="!textReport.trim() || isLifecycleRunning"
          >
            Submit →
          </button>
        </div>
      </div>

      <!-- ── Manual base64 fallback (dev) ─────────────── -->
      <details class="manual-fallback">
        <summary>Manual audio input (dev / testing)</summary>
        <textarea
          [(ngModel)]="manualAudioBase64"
          placeholder="Paste base64-encoded WAV audio here"
          rows="3"
        ></textarea>
        <button class="btn-secondary" (click)="submitManual()" [disabled]="isLifecycleRunning">
          Submit
        </button>
      </details>

      <!-- ── Lifecycle Progress Tracker ───────────────── -->
      <div class="lifecycle-tracker" *ngIf="currentSessionId">
        <div class="tracker-header">
          <span class="tracker-title">Encounter Pipeline</span>
          <code class="session-badge">{{ currentSessionId }}</code>
          <span class="tracker-state-badge" [class]="lifecycleStateBadgeClass">
            {{ lifecycleState }}
          </span>
        </div>

        <!-- Step progress bar -->
        <div class="steps-row">
          <div
            *ngFor="let step of visibleSteps; let i = index"
            class="step-item"
            [class.step-complete]="isStepComplete(step.state)"
            [class.step-active]="isStepActive(step.state)"
            [class.step-pending]="isStepPending(step.state)"
          >
            <div class="step-circle">
              <span *ngIf="isStepComplete(step.state)">✓</span>
              <span *ngIf="isStepActive(step.state)" class="spin">⟳</span>
              <span *ngIf="isStepPending(step.state)">{{ i + 1 }}</span>
            </div>
            <div class="step-label">{{ step.label }}</div>
            <div class="step-connector" *ngIf="i < visibleSteps.length - 1"></div>
          </div>
        </div>

        <!-- Clarification Gate UI -->
        <div class="gate-panel clarification-panel" *ngIf="lifecycleState === 'CLARIFICATION_GATE' && gateQuestion">
          <div class="gate-icon">❓</div>
          <p class="gate-question">{{ gateQuestion }}</p>
          <div class="gate-input-row">
            <input
              id="clarification-input"
              type="text"
              [(ngModel)]="clarificationAnswer"
              placeholder="Type your answer…"
              class="gate-text-input"
              (keyup.enter)="submitClarification()"
              [disabled]="clarificationSubmitting"
            />
            <button
              id="clarification-submit-btn"
              class="btn-gate-submit"
              (click)="submitClarification()"
              [disabled]="!clarificationAnswer.trim() || clarificationSubmitting"
            >
              <span *ngIf="!clarificationSubmitting">Send ↑</span>
              <span *ngIf="clarificationSubmitting" class="spin">⟳</span>
            </button>
          </div>
        </div>

        <!-- Decision Gate UI -->
        <div class="gate-panel decision-panel" *ngIf="lifecycleState === 'DECISION_GATE' && gateData">
          <div class="gate-icon">{{ gateData.triage_color === 'RED' ? '🔴' : '🟡' }}</div>
          <p class="gate-question">
            <strong>{{ gateData.triage_color }} TRIAGE</strong> — {{ gateData.summary || 'Patient requires referral' }}<br/>
            <small>Confirm to dispatch to nearest facility via Telegram.</small>
          </p>
          <div class="gate-actions">
            <button id="confirm-referral-btn" class="btn-confirm-gate" (click)="confirmDecision(true)">
              ✓ Approve &amp; Dispatch
            </button>
            <button id="decline-referral-btn" class="btn-decline-gate" (click)="confirmDecision(false)">
              ✕ Decline
            </button>
          </div>
          <p class="gate-countdown" *ngIf="gateData.triage_color === 'RED'">
            ⚠️ Auto-escalating in {{ gateTimeLeft }}s if no response
          </p>
        </div>

        <!-- Completed Summary Card -->
        <div class="result-card" *ngIf="lifecycleState === 'COMPLETE' && sessionData">
          <div class="triage-badge" [class]="triageBadgeClass">
            {{ sessionData.extracted?.triage_color || '—' }}
          </div>
          <div class="result-grid">
            <div class="result-item">
              <span class="rl">Syndrome</span>
              <span class="rv">{{ sessionData.extracted?.syndrome || '—' }}</span>
            </div>
            <div class="result-item">
              <span class="rl">Complaint</span>
              <span class="rv">{{ sessionData.extracted?.chief_complaint || '—' }}</span>
            </div>
            <div class="result-item">
              <span class="rl">Language</span>
              <span class="rv">{{ sessionData.extracted?.detected_language || '—' }}</span>
            </div>
            <div class="result-item">
              <span class="rl">Confidence</span>
              <span class="rv">{{ ((sessionData.extracted?.confidence || 0) * 100).toFixed(0) }}%</span>
            </div>
            <div class="result-item" *ngIf="sessionData.encounter_id">
              <span class="rl">Encounter ID</span>
              <span class="rv"><code>{{ sessionData.encounter_id }}</code></span>
            </div>
          </div>
        </div>

        <!-- Failed state -->
        <div class="error-panel" *ngIf="lifecycleState === 'FAILED'">
          ❌ {{ sessionData?.error || 'Encounter processing failed.' }}
          <button class="btn-secondary small" (click)="resetForm()">Try Again</button>
        </div>
      </div>

      <!-- ── Status Messages ────────────────────────────── -->
      <div class="error-msg" *ngIf="errorMsg" id="error-msg">⚠️ {{ errorMsg }}</div>
      <div class="offline-notice" *ngIf="queuedOffline">
        📴 Saved offline. Will sync automatically when connectivity returns.
      </div>
    </div>
  `,
  styles: [`
    .intake-container {
      max-width: 720px;
      margin: 0 auto;
      padding: 1.5rem;
      display: flex;
      flex-direction: column;
      gap: 1.5rem;
    }
    .intake-header h2 { margin: 0 0 .25rem; font-size: 1.4rem; }
    .intake-hint { margin: 0; opacity: .7; font-size: .9rem; }

    /* coords */
    .coords-row { display: flex; gap: .75rem; align-items: flex-end; flex-wrap: wrap; }
    .coord-label { display: flex; flex-direction: column; gap: .25rem; font-size: .85rem; }
    .coord-label input { padding: .4rem .6rem; border-radius: 6px; border: 1px solid rgba(255,255,255,.15);
      background: rgba(255,255,255,.07); color: inherit; width: 120px; }
    .btn-gps { padding: .45rem 1rem; border-radius: 8px; border: 1px solid rgba(255,255,255,.2);
      background: rgba(255,255,255,.08); color: inherit; cursor: pointer; font-size: .85rem;
      transition: background .2s; }
    .btn-gps:hover { background: rgba(255,255,255,.15); }
    .spinner-sm { display: inline-block; animation: spin 1s linear infinite; }

    /* recorder */
    .recorder-section { display: flex; flex-direction: column; align-items: center; gap: .75rem; }
    .btn-record {
      display: flex; align-items: center; gap: .75rem; padding: .9rem 2rem;
      border-radius: 50px; font-size: 1rem; font-weight: 600; cursor: pointer;
      border: 2px solid rgba(255,255,255,.2); background: rgba(255,255,255,.08);
      color: inherit; transition: all .2s; min-width: 200px; justify-content: center;
    }
    .btn-record:hover:not(:disabled) { background: rgba(255,255,255,.15); transform: translateY(-1px); }
    .btn-record.recording { background: rgba(239,68,68,.25); border-color: #ef4444;
      animation: pulse-border 1.2s ease-in-out infinite; }
    .btn-record.processing { opacity: .6; cursor: not-allowed; }
    .btn-record:disabled { opacity: .5; cursor: not-allowed; }
    .record-icon { font-size: 1.2rem; }
    .pulse-ring { animation: pulse-border 1s ease-in-out infinite; }
    @keyframes pulse-border { 0%,100% { opacity:1; } 50% { opacity:.5; } }

    .recording-wave { display: flex; gap: 3px; align-items: flex-end; height: 30px; }
    .wave-bar { width: 4px; background: #ef4444; border-radius: 2px;
      animation: wave 0.8s ease-in-out infinite alternate; }
    .wave-bar:nth-child(odd) { animation-delay: 0.15s; }
    @keyframes wave { from { height: 4px; } to { height: 28px; } }
    .record-timer { font-size: .85rem; opacity: .6; }

    /* text report */
    .text-report-section { display: flex; flex-direction: column; gap: .5rem; }
    .or-divider { text-align: center; position: relative; }
    .or-divider::before, .or-divider::after {
      content: ''; position: absolute; top: 50%; width: 42%; height: 1px;
      background: rgba(255,255,255,.12); }
    .or-divider::before { left: 0; } .or-divider::after { right: 0; }
    .or-divider span { font-size: .8rem; opacity: .5; background: transparent; padding: 0 .5rem; position: relative; }
    .text-input-row { display: flex; gap: .5rem; }
    .text-input-row textarea { flex: 1; padding: .6rem .8rem; border-radius: 10px;
      border: 1px solid rgba(255,255,255,.15); background: rgba(255,255,255,.07);
      color: inherit; resize: vertical; font-family: inherit; }
    .btn-text-submit { padding: .6rem 1.2rem; border-radius: 10px; border: none;
      background: linear-gradient(135deg, #6366f1, #8b5cf6); color: #fff;
      cursor: pointer; font-weight: 600; white-space: nowrap;
      transition: opacity .2s, transform .2s; }
    .btn-text-submit:hover:not(:disabled) { opacity: .85; transform: translateY(-1px); }
    .btn-text-submit:disabled { opacity: .4; cursor: not-allowed; }

    /* manual fallback */
    .manual-fallback { font-size: .85rem; opacity: .6; }
    .manual-fallback textarea { width: 100%; margin-top: .5rem; padding: .5rem;
      border-radius: 8px; border: 1px solid rgba(255,255,255,.1);
      background: rgba(255,255,255,.05); color: inherit; }
    .btn-secondary { padding: .35rem .8rem; border-radius: 6px; border: 1px solid rgba(255,255,255,.15);
      background: transparent; color: inherit; cursor: pointer; font-size: .8rem; margin-top: .25rem; }
    .btn-secondary.small { font-size: .78rem; }

    /* lifecycle tracker */
    .lifecycle-tracker { background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.1);
      border-radius: 14px; padding: 1.25rem; display: flex; flex-direction: column; gap: 1rem; }
    .tracker-header { display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; }
    .tracker-title { font-weight: 600; font-size: .9rem; }
    .session-badge { font-size: .72rem; background: rgba(255,255,255,.08); padding: .2rem .5rem;
      border-radius: 4px; opacity: .7; }
    .tracker-state-badge { font-size: .72rem; padding: .2rem .6rem; border-radius: 20px;
      font-weight: 700; letter-spacing: .04em; }
    .tracker-state-badge.state-running { background: rgba(99,102,241,.3); color: #a5b4fc; }
    .tracker-state-badge.state-gate { background: rgba(234,179,8,.25); color: #fde047; }
    .tracker-state-badge.state-complete { background: rgba(34,197,94,.2); color: #86efac; }
    .tracker-state-badge.state-failed { background: rgba(239,68,68,.25); color: #fca5a5; }
    .tracker-state-badge.state-idle { background: rgba(255,255,255,.08); color: rgba(255,255,255,.5); }

    /* steps */
    .steps-row { display: flex; align-items: flex-start; justify-content: space-between;
      overflow-x: auto; padding-bottom: .25rem; gap: 0; }
    .step-item { display: flex; flex-direction: column; align-items: center; gap: .3rem;
      flex: 1; position: relative; min-width: 60px; }
    .step-connector { position: absolute; top: 14px; left: 50%; width: 100%;
      height: 2px; background: rgba(255,255,255,.1); z-index: 0; }
    .step-circle { width: 28px; height: 28px; border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      font-size: .75rem; font-weight: 700; position: relative; z-index: 1;
      transition: all .3s; }
    .step-complete .step-circle { background: #22c55e; color: #fff; }
    .step-active .step-circle { background: rgba(99,102,241,.4); border: 2px solid #6366f1;
      color: #a5b4fc; animation: pulse-border 1.2s infinite; }
    .step-pending .step-circle { background: rgba(255,255,255,.07); border: 1px solid rgba(255,255,255,.15);
      color: rgba(255,255,255,.4); }
    .step-label { font-size: .68rem; opacity: .7; text-align: center; line-height: 1.2; }
    .step-complete .step-label { opacity: 1; }
    .step-active .step-label { opacity: 1; color: #a5b4fc; }

    /* gate panels */
    .gate-panel { border-radius: 12px; padding: 1rem 1.25rem;
      display: flex; flex-direction: column; gap: .75rem; align-items: flex-start; }
    .clarification-panel { background: rgba(234,179,8,.08); border: 1px solid rgba(234,179,8,.25); }
    .decision-panel { background: rgba(239,68,68,.07); border: 1px solid rgba(239,68,68,.25); }
    .gate-icon { font-size: 1.5rem; }
    .gate-question { margin: 0; font-size: .95rem; line-height: 1.5; }
    .gate-input-row { display: flex; gap: .5rem; width: 100%; }
    .gate-text-input { flex: 1; padding: .5rem .75rem; border-radius: 8px;
      border: 1px solid rgba(255,255,255,.15); background: rgba(255,255,255,.07);
      color: inherit; font-family: inherit; }
    .btn-gate-submit { padding: .5rem 1rem; border-radius: 8px; border: none;
      background: linear-gradient(135deg, #eab308, #f59e0b); color: #000;
      cursor: pointer; font-weight: 700; transition: opacity .2s; }
    .btn-gate-submit:disabled { opacity: .4; cursor: not-allowed; }
    .gate-actions { display: flex; gap: .75rem; }
    .btn-confirm-gate { padding: .55rem 1.2rem; border-radius: 8px; border: none;
      background: linear-gradient(135deg, #22c55e, #16a34a); color: #fff;
      cursor: pointer; font-weight: 700; transition: transform .2s; }
    .btn-confirm-gate:hover { transform: translateY(-1px); }
    .btn-decline-gate { padding: .55rem 1.2rem; border-radius: 8px;
      border: 1px solid rgba(239,68,68,.4); background: rgba(239,68,68,.1);
      color: #fca5a5; cursor: pointer; font-weight: 600; transition: background .2s; }
    .btn-decline-gate:hover { background: rgba(239,68,68,.2); }
    .gate-countdown { margin: 0; font-size: .8rem; opacity: .7; color: #f87171; }

    /* result card */
    .result-card { background: rgba(34,197,94,.07); border: 1px solid rgba(34,197,94,.2);
      border-radius: 12px; padding: 1rem 1.25rem; }
    .triage-badge { display: inline-block; padding: .25rem .75rem; border-radius: 20px;
      font-weight: 700; font-size: .8rem; letter-spacing: .05em; margin-bottom: .75rem; }
    .triage-red { background: rgba(239,68,68,.25); color: #fca5a5; }
    .triage-yellow { background: rgba(234,179,8,.25); color: #fde047; }
    .triage-green { background: rgba(34,197,94,.2); color: #86efac; }
    .result-grid { display: grid; grid-template-columns: 1fr 1fr; gap: .5rem .75rem; }
    .result-item { display: flex; flex-direction: column; gap: .1rem; }
    .rl { font-size: .72rem; opacity: .55; text-transform: uppercase; letter-spacing: .05em; }
    .rv { font-size: .9rem; font-weight: 500; }
    .rv code { font-size: .75rem; background: rgba(255,255,255,.08);
      padding: .1rem .35rem; border-radius: 4px; }

    /* error / offline */
    .error-panel { background: rgba(239,68,68,.1); border: 1px solid rgba(239,68,68,.25);
      border-radius: 10px; padding: .75rem 1rem; font-size: .9rem; color: #fca5a5;
      display: flex; align-items: center; gap: .75rem; }
    .error-msg { background: rgba(239,68,68,.1); border-radius: 8px;
      padding: .6rem .9rem; color: #fca5a5; font-size: .9rem; }
    .offline-notice { background: rgba(99,102,241,.1); border: 1px solid rgba(99,102,241,.25);
      border-radius: 8px; padding: .6rem .9rem; font-size: .9rem; color: #a5b4fc; }

    /* animations */
    .spin { display: inline-block; animation: spin 1s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }
  `],
})
export class IntakeComponent implements OnInit, OnDestroy {
  @Output() encounterStarted = new EventEmitter<string>();

  // Recording
  recordState: RecordingState = "idle";
  latitude = 0;
  longitude = 0;
  gpsLoading = false;
  textReport = "";
  manualAudioBase64 = "";

  // Lifecycle tracking
  currentSessionId = "";
  lifecycleState: LifecycleState = "IDLE";
  sessionData: any = null;
  gateQuestion = "";
  gateData: any = null;
  gateTimeLeft = 60;

  // Clarification
  clarificationAnswer = "";
  clarificationSubmitting = false;

  // Status
  errorMsg = "";
  queuedOffline = false;

  // UI candy
  waveBars: number[] = Array.from({ length: 12 }, () => 8);
  recordSeconds = 0;

  private mediaRecorder: MediaRecorder | null = null;
  private audioChunks: Blob[] = [];
  private pollInterval: any = null;
  private recordTimer: any = null;
  private waveTimer: any = null;
  private gateTimer: any = null;

  readonly visibleSteps = LIFECYCLE_STEPS;

  constructor(
    private api: ApiService,
    private syncService: OfflineSyncService
  ) {}

  ngOnInit() {}

  ngOnDestroy() {
    this.stopPolling();
    this.stopRecording();
    clearInterval(this.gateTimer);
  }

  // ── GPS ───────────────────────────────────────────────────────────────────

  getGPS() {
    if (!navigator.geolocation) {
      this.errorMsg = "Geolocation not supported.";
      return;
    }
    this.gpsLoading = true;
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        this.latitude = pos.coords.latitude;
        this.longitude = pos.coords.longitude;
        this.gpsLoading = false;
      },
      (err) => {
        this.errorMsg = `GPS error: ${err.message}`;
        this.gpsLoading = false;
      }
    );
  }

  // ── Recording ─────────────────────────────────────────────────────────────

  get isLifecycleRunning(): boolean {
    return (
      !!this.currentSessionId &&
      this.lifecycleState !== "COMPLETE" &&
      this.lifecycleState !== "FAILED" &&
      this.lifecycleState !== "IDLE"
    );
  }

  async toggleRecording() {
    if (this.recordState === "recording") {
      this.stopRecording();
    } else {
      await this.startRecording();
    }
  }

  private async startRecording() {
    this.errorMsg = "";
    this.queuedOffline = false;
    this.audioChunks = [];
    this.recordSeconds = 0;

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.mediaRecorder = new MediaRecorder(stream);
      this.mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) this.audioChunks.push(e.data);
      };
      this.mediaRecorder.onstop = () => this.onRecordingStop(stream);
      this.mediaRecorder.start();
      this.recordState = "recording";

      // Elapsed timer
      this.recordTimer = setInterval(() => this.recordSeconds++, 1000);

      // Fake wave animation
      this.waveTimer = setInterval(() => {
        this.waveBars = Array.from({ length: 12 }, () =>
          Math.floor(Math.random() * 24) + 4
        );
      }, 120);
    } catch (err: any) {
      this.errorMsg = `Microphone access denied: ${err.message}`;
      this.recordState = "error";
    }
  }

  private stopRecording() {
    clearInterval(this.recordTimer);
    clearInterval(this.waveTimer);
    if (this.mediaRecorder && this.mediaRecorder.state !== "inactive") {
      this.mediaRecorder.stop();
    }
  }

  private async onRecordingStop(stream: MediaStream) {
    stream.getTracks().forEach((t) => t.stop());
    this.recordState = "processing";
    const blob = new Blob(this.audioChunks, { type: "audio/webm" });
    const audioBase64 = await this.blobToBase64(blob);
    await this.submitAudio(audioBase64);
  }

  async submitManual() {
    if (!this.manualAudioBase64.trim()) return;
    this.recordState = "processing";
    await this.submitAudio(this.manualAudioBase64.trim());
  }

  async submitTextReport() {
    if (!this.textReport.trim()) return;
    this.errorMsg = "";
    this.queuedOffline = false;
    await this.launchLifecycle({ text: this.textReport.trim() });
  }

  // ── Lifecycle launch ─────────────────────────────────────────────────────

  private async submitAudio(audioBase64: string) {
    if (!navigator.onLine) {
      const sid = this.makeSessionId();
      this.syncService.queueEncounter({
        session_id: sid,
        audio_base64: audioBase64,
        latitude: this.latitude,
        longitude: this.longitude,
      });
      this.queuedOffline = true;
      this.recordState = "done";
      return;
    }
    await this.launchLifecycle({ audio: audioBase64 });
    this.recordState = "done";
  }

  private async launchLifecycle(input: { audio?: string; text?: string }) {
    const sid = this.makeSessionId();
    this.currentSessionId = sid;
    this.lifecycleState = "LISTENING";
    this.sessionData = null;
    this.gateQuestion = "";
    this.gateData = null;
    this.encounterStarted.emit(sid);

    const body: any = {
      session_id: sid,
      latitude: this.latitude,
      longitude: this.longitude,
    };

    if (input.audio) {
      body.audio_base64 = input.audio;
    } else if (input.text) {
      body.form_data = {
        chief_complaint: input.text,
        source: "web_text",
      };
    }

    try {
      await this.api.post("/encounter/start", body);
      this.startPolling(sid);
    } catch (err: any) {
      this.errorMsg = `Failed to start encounter: ${err.message}`;
      this.lifecycleState = "FAILED";
      if (input.audio) {
        this.syncService.queueEncounter({ ...body, audio_base64: input.audio });
        this.queuedOffline = true;
      }
    }
  }

  // ── Polling ────────────────────────────────────────────────────────────────

  private startPolling(sessionId: string) {
    this.stopPolling();
    this.pollInterval = setInterval(() => this.pollStatus(sessionId), 2000);
  }

  private stopPolling() {
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
    }
  }

  private async pollStatus(sessionId: string) {
    try {
      const res = await this.api.getEncounterStatus(sessionId);
      this.lifecycleState = res.state as LifecycleState;
      this.sessionData = res.data || null;

      // Handle clarification gate
      if (this.lifecycleState === "CLARIFICATION_GATE") {
        this.gateQuestion = res.data?.gate_data?.question || "Please provide more details.";
      }

      // Handle decision gate
      if (this.lifecycleState === "DECISION_GATE") {
        this.gateData = res.data?.gate_data || null;
        this.startGateCountdown();
      }

      // Terminal states — stop polling
      if (
        this.lifecycleState === "COMPLETE" ||
        this.lifecycleState === "FAILED" ||
        this.lifecycleState === "OFFLINE_QUEUED"
      ) {
        this.stopPolling();
        clearInterval(this.gateTimer);
      }
    } catch {
      // Swallow poll errors silently — session may not exist yet
    }
  }

  // ── Gate actions ─────────────────────────────────────────────────────────

  async submitClarification() {
    if (!this.clarificationAnswer.trim() || this.clarificationSubmitting) return;
    this.clarificationSubmitting = true;
    try {
      await this.api.post(`/encounter/${this.currentSessionId}/clarify`, {
        answer: this.clarificationAnswer.trim(),
      });
      this.clarificationAnswer = "";
      this.gateQuestion = "";
    } catch (err: any) {
      this.errorMsg = `Clarification failed: ${err.message}`;
    } finally {
      this.clarificationSubmitting = false;
    }
  }

  async confirmDecision(confirmed: boolean) {
    try {
      await this.api.confirmEncounter(this.currentSessionId, confirmed);
      this.gateData = null;
      clearInterval(this.gateTimer);
    } catch (err: any) {
      this.errorMsg = `Could not submit decision: ${err.message}`;
    }
  }

  private startGateCountdown() {
    clearInterval(this.gateTimer);
    this.gateTimeLeft = 60;
    this.gateTimer = setInterval(() => {
      this.gateTimeLeft--;
      if (this.gateTimeLeft <= 0) clearInterval(this.gateTimer);
    }, 1000);
  }

  // ── Step helpers ──────────────────────────────────────────────────────────

  private readonly STEP_ORDER: LifecycleState[] = [
    "LISTENING", "EXTRACTING", "CLARIFICATION_GATE", "GEOCODING",
    "STORING", "FOLLOW_UP_SCHEDULED", "ALERTING", "DECISION_GATE",
    "NOTIFYING", "COMPLETE",
  ];

  isStepComplete(state: LifecycleState): boolean {
    const cur = this.STEP_ORDER.indexOf(this.lifecycleState);
    const s = this.STEP_ORDER.indexOf(state);
    return cur > s && this.lifecycleState !== "FAILED";
  }

  isStepActive(state: LifecycleState): boolean {
    return (
      this.lifecycleState === state &&
      this.lifecycleState !== "COMPLETE" &&
      this.lifecycleState !== "FAILED"
    );
  }

  isStepPending(state: LifecycleState): boolean {
    return !this.isStepComplete(state) && !this.isStepActive(state);
  }

  get lifecycleStateBadgeClass(): string {
    if (this.lifecycleState === "COMPLETE") return "tracker-state-badge state-complete";
    if (this.lifecycleState === "FAILED") return "tracker-state-badge state-failed";
    if (
      this.lifecycleState === "CLARIFICATION_GATE" ||
      this.lifecycleState === "DECISION_GATE"
    ) return "tracker-state-badge state-gate";
    if (this.lifecycleState === "IDLE") return "tracker-state-badge state-idle";
    return "tracker-state-badge state-running";
  }

  get triageBadgeClass(): string {
    const c = this.sessionData?.extracted?.triage_color;
    return c === "RED" ? "triage-badge triage-red"
         : c === "YELLOW" ? "triage-badge triage-yellow"
         : "triage-badge triage-green";
  }

  resetForm() {
    this.currentSessionId = "";
    this.lifecycleState = "IDLE";
    this.sessionData = null;
    this.gateQuestion = "";
    this.gateData = null;
    this.errorMsg = "";
    this.queuedOffline = false;
    this.recordState = "idle";
    this.textReport = "";
    this.stopPolling();
    clearInterval(this.gateTimer);
  }

  // ── Utilities ─────────────────────────────────────────────────────────────

  private makeSessionId(): string {
    return `CHV-${Date.now()}`;
  }

  private blobToBase64(blob: Blob): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () => {
        const dataUrl = reader.result as string;
        resolve(dataUrl.split(",")[1] ?? dataUrl);
      };
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }
}
