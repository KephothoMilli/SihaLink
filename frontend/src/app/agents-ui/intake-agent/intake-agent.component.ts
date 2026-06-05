/**
 * Intake Agent UI Component — Angular Material 3
 *
 * Three intake modes on a Material tab group:
 *   1. Voice Recording  — mic → Gemini transcription + clinical extraction
 *   2. Web Form         — structured clinical fields + symptom chips
 *   3. Telegram Relay   — paste CHV message text for server-side processing
 */

import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subject } from 'rxjs';

// Angular Material
import { MatTabsModule } from '@angular/material/tabs';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatChipsModule } from '@angular/material/chips';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatDividerModule } from '@angular/material/divider';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatBadgeModule } from '@angular/material/badge';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';

import {
  IntakeAgentService,
  ExtractionResult,
  FormIntakeRequest,
  TelegramIntakeRequest,
} from '../../../services/agents/intake-agent.service';
import { ApiService } from '../../../services/api.service';

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
  'unknown',
];

@Component({
  selector: 'app-intake-agent',
  templateUrl: './intake-agent.component.html',
  styleUrl: './intake-agent.component.scss',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    // Material
    MatTabsModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatChipsModule,
    MatProgressSpinnerModule,
    MatProgressBarModule,
    MatDividerModule,
    MatTooltipModule,
    MatBadgeModule,
    MatSnackBarModule,
  ],
})
export class IntakeAgentComponent implements OnInit, OnDestroy {
  // ── shared state ──────────────────────────────────────────────────────────
  isProcessing = false;
  extractionResult: ExtractionResult | null = null;
  clarificationText = '';

  // ── audio tab ─────────────────────────────────────────────────────────────
  isRecording = false;
  recordingTime = 0;
  audioBlob: Blob | null = null;
  micAvailable = true;
  private mediaRecorder: MediaRecorder | null = null;
  private audioChunks: Blob[] = [];
  private recordingTimer: ReturnType<typeof setInterval> | null = null;

  // ── form tab ──────────────────────────────────────────────────────────────
  readonly counties = KENYA_COUNTIES;
  readonly syndromes = WHO_SYNDROMES;
  formData = {
    chief_complaint: '',
    age_value: null as number | null,
    age_unit: 'years' as 'years' | 'months' | 'weeks' | 'days',
    sex: '' as '' | 'male' | 'female' | 'unknown',
    temperature_c: null as number | null,
    respiratory_rate: null as number | null,
    heart_rate: null as number | null,
    duration_days: null as number | null,
    syndrome_hint: '',
    language_hint: '',
    county: '',
    patient_contacts: '',
    symptoms: [] as string[],
  };
  symptomInput = '';

  // ── telegram relay tab ────────────────────────────────────────────────────
  telegramData = {
    chw_id: '',
    message_text: '',
    language_hint: '',
  };

  // ── agent logs ────────────────────────────────────────────────────────────
  agentLogs: any[] = [];
  private logPollInterval: any;

  private destroy$ = new Subject<void>();

  constructor(
    private intakeAgent: IntakeAgentService,
    private api: ApiService,
    private snackBar: MatSnackBar,
  ) {}

  ngOnInit() {
    this.setupAudioRecording();
    this.startLogPolling();
  }

  ngOnDestroy() {
    this.stopRecording();
    if (this.logPollInterval) clearInterval(this.logPollInterval);
    this.destroy$.next();
    this.destroy$.complete();
  }

  private startLogPolling() {
    this.fetchLogs();
    this.logPollInterval = setInterval(() => this.fetchLogs(), 3000);
  }

  private async fetchLogs() {
    try {
      const res = await this.api.getAgentLogs(undefined, 5);
      if (res && res.logs) {
        this.agentLogs = res.logs;
      }
    } catch (e) {
      // Ignore polling errors
    }
  }

  // ── Audio ─────────────────────────────────────────────────────────────────

  private async setupAudioRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm';
      this.mediaRecorder = new MediaRecorder(stream, { mimeType });
      this.mediaRecorder.ondataavailable = (e: BlobEvent) => {
        if (e.data.size > 0) this.audioChunks.push(e.data);
      };
      this.mediaRecorder.onstop = () => {
        this.audioBlob = new Blob(this.audioChunks, {
          type: this.mediaRecorder!.mimeType,
        });
        this.audioChunks = [];
      };
    } catch {
      this.micAvailable = false;
    }
  }

  startRecording() {
    if (!this.mediaRecorder) {
      this.showError('Microphone not available. Check browser permissions.');
      return;
    }
    this.audioChunks = [];
    this.audioBlob = null;
    this.mediaRecorder.start(250);
    this.isRecording = true;
    this.recordingTime = 0;
    this.recordingTimer = setInterval(() => this.recordingTime++, 1000);
  }

  stopRecording() {
    if (this.mediaRecorder && this.isRecording) {
      this.mediaRecorder.stop();
      this.isRecording = false;
      if (this.recordingTimer) {
        clearInterval(this.recordingTimer);
        this.recordingTimer = null;
      }
    }
  }

  async processAudio() {
    if (!this.audioBlob) {
      this.showError('No audio recorded.');
      return;
    }
    this.isProcessing = true;
    try {
      const b64 = await this.blobToBase64(this.audioBlob);
      this.extractionResult = await this.intakeAgent.extractClinicalData({
        audio_base64: b64,
      });
    } catch (err) {
      this.showError(
        err instanceof Error ? err.message : 'Audio processing failed',
      );
    } finally {
      this.isProcessing = false;
    }
  }

  getRecordingTimeDisplay(): string {
    const m = Math.floor(this.recordingTime / 60);
    const s = this.recordingTime % 60;
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  private blobToBase64(blob: Blob): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () =>
        resolve((reader.result as string).split(',')[1] ?? '');
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }

  // ── Web form ──────────────────────────────────────────────────────────────

  addSymptom() {
    const s = this.symptomInput.trim();
    if (s && !this.formData.symptoms.includes(s)) {
      this.formData.symptoms = [...this.formData.symptoms, s];
    }
    this.symptomInput = '';
  }

  removeSymptom(s: string) {
    this.formData.symptoms = this.formData.symptoms.filter((x) => x !== s);
  }

  async submitForm() {
    if (
      !this.formData.chief_complaint.trim() &&
      this.formData.symptoms.length === 0
    ) {
      this.showError('Enter a chief complaint or at least one symptom.');
      return;
    }
    this.isProcessing = true;
    try {
      const req: FormIntakeRequest = {
        chief_complaint: this.formData.chief_complaint,
        symptoms: this.formData.symptoms,
        age_value: this.formData.age_value ?? undefined,
        age_unit: this.formData.age_unit,
        sex: this.formData.sex || undefined,
        temperature_c: this.formData.temperature_c ?? undefined,
        respiratory_rate: this.formData.respiratory_rate ?? undefined,
        heart_rate: this.formData.heart_rate ?? undefined,
        duration_days: this.formData.duration_days ?? undefined,
        syndrome_hint: this.formData.syndrome_hint || undefined,
        language_hint: this.formData.language_hint || undefined,
        county: this.formData.county || undefined,
        patient_contacts: this.formData.patient_contacts || undefined,
      };
      this.extractionResult = await this.intakeAgent.submitForm(req);
    } catch (err) {
      this.showError(
        err instanceof Error ? err.message : 'Form submission failed',
      );
    } finally {
      this.isProcessing = false;
    }
  }

  // ── Telegram relay ────────────────────────────────────────────────────────

  async relayTelegramMessage() {
    if (!this.telegramData.message_text.trim()) {
      this.showError('Paste the Telegram message text.');
      return;
    }
    this.isProcessing = true;
    try {
      const req: TelegramIntakeRequest = {
        chw_id: this.telegramData.chw_id || 'web-relay',
        message_text: this.telegramData.message_text,
        language_hint: this.telegramData.language_hint || undefined,
      };
      this.extractionResult = await this.intakeAgent.relayTelegramMessage(req);
    } catch (err) {
      this.showError(
        err instanceof Error ? err.message : 'Telegram relay failed',
      );
    } finally {
      this.isProcessing = false;
    }
  }

  // ── Clarification ─────────────────────────────────────────────────────────

  async submitClarification() {
    if (!this.clarificationText.trim() || !this.extractionResult) return;
    this.isProcessing = true;
    try {
      this.extractionResult = await this.intakeAgent.clarifyExtraction({
        original_extraction: this.extractionResult,
        clarification_answer: this.clarificationText.trim(),
      });
      this.clarificationText = '';
    } catch (err) {
      this.showError(
        err instanceof Error ? err.message : 'Clarification failed',
      );
    } finally {
      this.isProcessing = false;
    }
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  reset() {
    this.extractionResult = null;
    this.audioBlob = null;
    this.clarificationText = '';
    this.symptomInput = '';
    this.formData = {
      chief_complaint: '',
      age_value: null,
      age_unit: 'years',
      sex: '',
      temperature_c: null,
      respiratory_rate: null,
      heart_rate: null,
      duration_days: null,
      syndrome_hint: '',
      language_hint: '',
      county: '',
      patient_contacts: '',
      symptoms: [],
    };
    this.telegramData = { chw_id: '', message_text: '', language_hint: '' };
  }

  triageColor(triage: string | undefined): string {
    switch (triage) {
      case 'RED':
        return 'var(--mat-sys-error)';
      case 'YELLOW':
        return '#f59e0b';
      case 'GREEN':
        return '#16a34a';
      default:
        return 'var(--mat-sys-outline)';
    }
  }

  triageIcon(triage: string | undefined): string {
    switch (triage) {
      case 'RED':
        return 'emergency';
      case 'YELLOW':
        return 'warning';
      case 'GREEN':
        return 'check_circle';
      default:
        return 'help';
    }
  }

  formatSyndrome(s: string | undefined): string {
    return (s ?? 'unknown').replace(/_/g, ' ');
  }

  private showError(msg: string) {
    this.snackBar.open(msg, 'Dismiss', {
      duration: 5000,
      panelClass: ['snack-error'],
      horizontalPosition: 'center',
      verticalPosition: 'bottom',
    });
  }
}
