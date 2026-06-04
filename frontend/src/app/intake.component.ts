import { Component, EventEmitter, OnDestroy, Output } from "@angular/core";
import { CommonModule } from "@angular/common";
import { FormsModule } from "@angular/forms";
import { ApiService } from "../services/api.service";
import { OfflineSyncService } from "../services/offline-sync.service";

type RecordingState = "idle" | "recording" | "processing" | "done" | "error";

@Component({
  selector: "app-intake",
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="intake-container">
      <h2>🎙️ Voice Intake</h2>
      <p class="intake-hint">
        Speak in any language: Dholuo, Swahili, Kikuyu, Somali, or English.
      </p>

      <!-- GPS coordinates -->
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
        <button class="btn-gps" (click)="getGPS()" title="Use device GPS">
          📍 GPS
        </button>
      </div>

      <!-- Recording controls -->
      <div class="recorder-controls">
        <button
          class="btn-record"
          [class.recording]="state === 'recording'"
          [disabled]="state === 'processing'"
          (click)="toggleRecording()"
        >
          <span *ngIf="state === 'idle'">🎙️ Start Recording</span>
          <span *ngIf="state === 'recording'">⏹️ Stop Recording</span>
          <span *ngIf="state === 'processing'">⏳ Processing...</span>
          <span *ngIf="state === 'done'">🎙️ Record Again</span>
          <span *ngIf="state === 'error'">🎙️ Retry</span>
        </button>

        <div class="recording-indicator" *ngIf="state === 'recording'">
          <span class="pulse-dot"></span> Recording...
        </div>
      </div>

      <!-- Manual base64 fallback -->
      <details class="manual-fallback">
        <summary>Manual audio input (dev/testing)</summary>
        <textarea
          [(ngModel)]="manualAudioBase64"
          placeholder="Paste base64-encoded WAV audio here"
          rows="3"
        ></textarea>
        <button class="btn-secondary" (click)="submitManual()">Submit</button>
      </details>

      <!-- Result display -->
      <div class="result-card" *ngIf="result">
        <div class="triage-badge" [class]="triageClass">
          {{ result.extracted?.triage_color || "UNKNOWN" }}
        </div>
        <h3>Extracted Clinical Data</h3>
        <table class="result-table">
          <tr>
            <td>Language</td>
            <td>{{ result.extracted?.language || "—" }}</td>
          </tr>
          <tr>
            <td>Syndrome</td>
            <td>{{ result.extracted?.syndrome || "—" }}</td>
          </tr>
          <tr>
            <td>Symptoms</td>
            <td>
              {{ (result.extracted?.primary_symptoms || []).join(", ") || "—" }}
            </td>
          </tr>
          <tr>
            <td>Severity</td>
            <td>{{ result.extracted?.severity || "—" }}</td>
          </tr>
          <tr>
            <td>Chief Complaint</td>
            <td>{{ result.extracted?.chief_complaint || "—" }}</td>
          </tr>
          <tr>
            <td>Confidence</td>
            <td>
              {{ ((result.extracted?.confidence || 0) * 100).toFixed(0) }}%
            </td>
          </tr>
        </table>
        <div class="session-id">
          Session: <code>{{ currentSessionId }}</code>
        </div>
      </div>

      <div class="error-msg" *ngIf="errorMsg">⚠️ {{ errorMsg }}</div>
      <div class="offline-notice" *ngIf="queuedOffline">
        📴 Saved offline. Will sync when connectivity returns.
      </div>
    </div>
  `,
})
export class IntakeComponent implements OnDestroy {
  @Output() encounterStarted = new EventEmitter<string>();

  state: RecordingState = "idle";
  latitude = 0;
  longitude = 0;
  result: any = null;
  errorMsg = "";
  queuedOffline = false;
  currentSessionId = "";
  manualAudioBase64 = "";

  private mediaRecorder: MediaRecorder | null = null;
  private audioChunks: Blob[] = [];

  constructor(
    private api: ApiService,
    private syncService: OfflineSyncService,
  ) { }

  ngOnDestroy() {
    this.stopRecording();
  }

  getGPS() {
    if (!navigator.geolocation) {
      this.errorMsg = "Geolocation not supported by this browser.";
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        this.latitude = pos.coords.latitude;
        this.longitude = pos.coords.longitude;
      },
      (err) => {
        this.errorMsg = `GPS error: ${err.message}`;
      },
    );
  }

  async toggleRecording() {
    if (this.state === "recording") {
      this.stopRecording();
    } else {
      await this.startRecording();
    }
  }

  private async startRecording() {
    this.errorMsg = "";
    this.queuedOffline = false;
    this.result = null;
    this.audioChunks = [];

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.mediaRecorder = new MediaRecorder(stream);
      this.mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) this.audioChunks.push(e.data);
      };
      this.mediaRecorder.onstop = () => this.onRecordingStop(stream);
      this.mediaRecorder.start();
      this.state = "recording";
    } catch (err: any) {
      this.errorMsg = `Microphone access denied: ${err.message}`;
      this.state = "error";
    }
  }

  private stopRecording() {
    if (this.mediaRecorder && this.mediaRecorder.state !== "inactive") {
      this.mediaRecorder.stop();
    }
  }

  private async onRecordingStop(stream: MediaStream) {
    // Stop all tracks to release the microphone
    stream.getTracks().forEach((t) => t.stop());
    this.state = "processing";

    const blob = new Blob(this.audioChunks, { type: "audio/webm" });
    const audioBase64 = await this.blobToBase64(blob);
    await this.submitAudio(audioBase64);
  }

  async submitManual() {
    if (!this.manualAudioBase64.trim()) return;
    this.state = "processing";
    await this.submitAudio(this.manualAudioBase64.trim());
  }

  private async submitAudio(audioBase64: string) {
    this.currentSessionId = `CHV-${Date.now()}`;
    const payload = {
      session_id: this.currentSessionId,
      audio_base64: audioBase64,
      latitude: this.latitude,
      longitude: this.longitude,
    };

    if (!navigator.onLine) {
      this.syncService.queueEncounter(payload);
      this.queuedOffline = true;
      this.state = "done";
      return;
    }

    try {
      const res = await this.api.startEncounter(payload);
      this.encounterStarted.emit(this.currentSessionId);

      // Also extract clinical data for immediate display
      const extracted = await this.api.extractClinicalData({
        audio_base64: audioBase64,
      });
      this.result = extracted;
      this.state = "done";
    } catch (err: any) {
      this.errorMsg = `Submission failed: ${err.message}`;
      this.state = "error";
      // Queue offline as fallback
      this.syncService.queueEncounter(payload);
      this.queuedOffline = true;
    }
  }

  get triageClass(): string {
    const color = this.result?.extracted?.triage_color;
    return color === "RED"
      ? "triage-red"
      : color === "YELLOW"
        ? "triage-yellow"
        : "triage-green";
  }

  private blobToBase64(blob: Blob): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () => {
        const dataUrl = reader.result as string;
        // Strip the data URL prefix
        resolve(dataUrl.split(",")[1] ?? dataUrl);
      };
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }
}
