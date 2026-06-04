/**
 * RecorderComponent — SihaLink Web
 * Handles microphone recording via the Web MediaRecorder API,
 * captures GPS coordinates, and queues the encounter for processing.
 */

import { Component, EventEmitter, OnDestroy, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ApiService } from '../../../services/api.service';
import { OfflineSyncService } from '../../../services/offline-sync.service';

type RecordingState = 'idle' | 'recording' | 'processing' | 'done' | 'error';

@Component({
  selector: 'app-recorder',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="recorder-wrapper">
      <div class="recorder-controls">
        <button
          class="btn-record"
          [class.recording]="state === 'recording'"
          [disabled]="state === 'processing'"
          (click)="toggleRecording()"
          [attr.aria-label]="recordingAriaLabel"
        >
          <span *ngIf="state === 'idle'">🎙️ Start Recording</span>
          <span *ngIf="state === 'recording'">⏹️ Stop Recording</span>
          <span *ngIf="state === 'processing'">⏳ Processing…</span>
          <span *ngIf="state === 'done'">🎙️ Record Again</span>
          <span *ngIf="state === 'error'">🎙️ Retry</span>
        </button>

        <div
          class="recording-indicator"
          *ngIf="state === 'recording'"
          aria-live="polite"
        >
          <span class="pulse-dot"></span> Recording…
        </div>
      </div>

      <div class="error-msg" *ngIf="errorMsg" role="alert">
        ⚠️ {{ errorMsg }}
      </div>
      <div class="offline-notice" *ngIf="queuedOffline" aria-live="polite">
        📴 Saved offline. Will sync when connectivity returns.
      </div>
    </div>
  `,
})
export class RecorderComponent implements OnDestroy {
  /** Emits the session_id once an encounter has been submitted */
  @Output() encounterStarted = new EventEmitter<string>();
  /** Emits the raw base64 audio + GPS so the parent can display extracted results */
  @Output() audioReady = new EventEmitter<{
    audioBase64: string;
    latitude: number;
    longitude: number;
    sessionId: string;
  }>();

  state: RecordingState = 'idle';
  errorMsg = '';
  queuedOffline = false;

  private mediaRecorder: MediaRecorder | null = null;
  private audioChunks: Blob[] = [];
  private latitude = 0;
  private longitude = 0;

  constructor(
    private api: ApiService,
    private syncService: OfflineSyncService,
  ) {}

  ngOnDestroy() {
    this.stopRecording();
  }

  get recordingAriaLabel(): string {
    const labels: Record<RecordingState, string> = {
      idle: 'Start voice recording',
      recording: 'Stop voice recording',
      processing: 'Processing audio',
      done: 'Start a new recording',
      error: 'Retry recording',
    };
    return labels[this.state];
  }

  async toggleRecording() {
    if (this.state === 'recording') {
      this.stopRecording();
    } else {
      await this.startRecording();
    }
  }

  private async startRecording() {
    this.errorMsg = '';
    this.queuedOffline = false;
    this.audioChunks = [];

    // Capture GPS before recording starts
    await this.captureGPS();

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.mediaRecorder = new MediaRecorder(stream);
      this.mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) this.audioChunks.push(e.data);
      };
      this.mediaRecorder.onstop = () => this.onRecordingStop(stream);
      this.mediaRecorder.start();
      this.state = 'recording';
    } catch (err: any) {
      this.errorMsg = `Microphone access denied: ${err.message}`;
      this.state = 'error';
    }
  }

  private stopRecording() {
    if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
      this.mediaRecorder.stop();
    }
  }

  private async onRecordingStop(stream: MediaStream) {
    stream.getTracks().forEach((t) => t.stop());
    this.state = 'processing';

    const blob = new Blob(this.audioChunks, { type: 'audio/webm' });
    const audioBase64 = await this.blobToBase64(blob);
    await this.submitAudio(audioBase64);
  }

  private async submitAudio(audioBase64: string) {
    const sessionId = `CHV-${Date.now()}`;
    const payload = {
      session_id: sessionId,
      audio_base64: audioBase64,
      latitude: this.latitude,
      longitude: this.longitude,
    };

    if (!navigator.onLine) {
      this.syncService.queueEncounter(payload);
      this.queuedOffline = true;
      this.state = 'done';
      return;
    }

    try {
      await this.api.startEncounter(payload);
      this.encounterStarted.emit(sessionId);
      this.audioReady.emit({
        audioBase64,
        latitude: this.latitude,
        longitude: this.longitude,
        sessionId,
      });
      this.state = 'done';
    } catch (err: any) {
      this.errorMsg = `Submission failed: ${err.message}`;
      this.state = 'error';
      // Fallback: queue offline
      this.syncService.queueEncounter(payload);
      this.queuedOffline = true;
    }
  }

  private captureGPS(): Promise<void> {
    return new Promise((resolve) => {
      if (!navigator.geolocation) {
        resolve();
        return;
      }
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          this.latitude = pos.coords.latitude;
          this.longitude = pos.coords.longitude;
          resolve();
        },
        () => resolve(), // GPS failure is non-fatal
        { timeout: 5000 },
      );
    });
  }

  private blobToBase64(blob: Blob): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () => {
        const dataUrl = reader.result as string;
        resolve(dataUrl.split(',')[1] ?? dataUrl);
      };
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }
}
