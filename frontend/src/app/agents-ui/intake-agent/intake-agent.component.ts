/**
 * Intake Agent UI Component
 * Interface for recording audio and extracting clinical data via Gemini Live API.
 */

import {
  Component,
  OnInit,
  OnDestroy,
  ViewChild,
  ElementRef,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subject } from 'rxjs';
import {
  IntakeAgentService,
  ExtractionResult,
} from '../../../services/agents/intake-agent.service';

@Component({
  selector: 'app-intake-agent',
  templateUrl: './intake-agent.component.html',
  styleUrl: './intake-agent.component.css',
  standalone: true,
  imports: [CommonModule, FormsModule],
})
export class IntakeAgentComponent implements OnInit, OnDestroy {
  @ViewChild('audioElement') audioElement: ElementRef | null = null;

  isRecording = false;
  isProcessing = false;
  extractionResult: ExtractionResult | null = null;
  error: string | null = null;
  recordingTime = 0;
  audioBlob: Blob | null = null;
  clarificationText = '';

  private mediaRecorder: MediaRecorder | null = null;
  private audioChunks: Blob[] = [];
  private recordingTimer: ReturnType<typeof setInterval> | null = null;
  private destroy$ = new Subject<void>();

  constructor(private intakeAgent: IntakeAgentService) {}

  ngOnInit() {
    this.setupAudioRecording();
  }

  ngOnDestroy() {
    this.stopRecording();
    this.destroy$.next();
    this.destroy$.complete();
  }

  private async setupAudioRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.mediaRecorder = new MediaRecorder(stream);
      this.mediaRecorder.ondataavailable = (event: BlobEvent) => {
        this.audioChunks.push(event.data);
      };
      this.mediaRecorder.onstop = () => {
        this.audioBlob = new Blob(this.audioChunks, { type: 'audio/wav' });
        this.audioChunks = [];
      };
    } catch (error) {
      this.error = 'Failed to access microphone. Please check permissions.';
    }
  }

  startRecording() {
    if (!this.mediaRecorder) {
      this.error = 'Microphone not initialized';
      return;
    }
    this.audioChunks = [];
    this.mediaRecorder.start();
    this.isRecording = true;
    this.error = null;
    this.recordingTime = 0;
    this.recordingTimer = setInterval(() => this.recordingTime++, 1000);
  }

  stopRecording() {
    if (this.mediaRecorder && this.isRecording) {
      this.mediaRecorder.stop();
      this.isRecording = false;
      if (this.recordingTimer) clearInterval(this.recordingTimer);
    }
  }

  async processAudio() {
    if (!this.audioBlob) {
      this.error = 'No audio recorded';
      return;
    }
    this.isProcessing = true;
    this.error = null;
    try {
      const base64Audio = await this.blobToBase64(this.audioBlob);
      this.extractionResult = await this.intakeAgent.extractClinicalData({
        audio_base64: base64Audio,
      });
    } catch (err: unknown) {
      this.error =
        err instanceof Error ? err.message : 'Failed to process audio';
    } finally {
      this.isProcessing = false;
    }
  }

  async clarifyExtraction(clarificationAnswer: string) {
    if (!this.extractionResult) return;
    this.isProcessing = true;
    try {
      this.extractionResult = await this.intakeAgent.clarifyExtraction({
        original_extraction: this.extractionResult,
        clarification_answer: clarificationAnswer,
      });
    } catch (err: unknown) {
      this.error = err instanceof Error ? err.message : 'Clarification failed';
    } finally {
      this.isProcessing = false;
    }
  }

  async submitClarification() {
    if (!this.clarificationText.trim()) return;
    await this.clarifyExtraction(this.clarificationText.trim());
    this.clarificationText = '';
  }

  resetExtraction() {
    this.extractionResult = null;
    this.audioBlob = null;
    this.error = null;
  }

  getRecordingTimeDisplay(): string {
    const m = Math.floor(this.recordingTime / 60);
    const s = this.recordingTime % 60;
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
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
