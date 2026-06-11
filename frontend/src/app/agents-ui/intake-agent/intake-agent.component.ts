/**
 * Intake Agent Component — Swarm Workflow Stepper
 *
 * Gate-protected clinical intake portal for qualified CHWs and Clinicians.
 * Captures device GPS coordinates for precise geo-enrichment.
 *
 * Workflow (mirrors APP_WORKFLOW.md encounter pipeline):
 *   Step 0 — Identity Verification  (CHW/Clinician credential check)
 *   Step 1 — Patient Information     (demographics, location, language)
 *   Step 2 — Clinical Intake         (voice | form | Telegram relay)
 *   Step 3 — Swarm Processing        (live pipeline: extract → geo → store)
 *   Step 4 — Review & Dispatch       (triage result, referral gate, protocol)
 */

import {
  Component,
  OnInit,
  OnDestroy,
  ViewChild,
  ChangeDetectorRef,
} from '@angular/core';
import { CommonModule, DecimalPipe } from '@angular/common';
import {
  FormsModule,
  ReactiveFormsModule,
  FormBuilder,
  FormGroup,
  Validators,
} from '@angular/forms';
import { Subject, interval } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

// Angular Material
import { MatStepperModule, MatStepper } from '@angular/material/stepper';
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
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatRadioModule } from '@angular/material/radio';
import { MatBadgeModule } from '@angular/material/badge';

import {
  IntakeAgentService,
  ExtractionResult,
  FormIntakeRequest,
} from '../../../services/agents/intake-agent.service';
import { RootAgentService } from '../../../services/root-agent.service';
import { ApiService } from '../../../services/api.service';
import { Router } from '@angular/router';

export type UserRole = 'chw' | 'clinician' | null;

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
    DecimalPipe,
    FormsModule,
    ReactiveFormsModule,
    MatStepperModule,
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
    MatSnackBarModule,
    MatRadioModule,
    MatBadgeModule,
  ],
})
export class IntakeAgentComponent implements OnInit, OnDestroy {
  @ViewChild('stepper') stepper!: MatStepper;

  readonly counties = KENYA_COUNTIES;
  readonly syndromes = WHO_SYNDROMES;

  // ── Step 0 — Identity gate ────────────────────────────────────────────
  identityForm!: FormGroup;
  role: UserRole = null;
  identityVerified = false;
  verifying = false;

  // ── Step 1 — Patient info ─────────────────────────────────────────────
  patientForm!: FormGroup;
  symptomInput = '';
  symptoms: string[] = [];

  // ── Step 2 — Intake mode ──────────────────────────────────────────────
  intakeMode: 'voice' | 'form' | 'telegram' = 'voice';

  setIntakeMode(mode: 'voice' | 'form' | 'telegram') {
    this.intakeMode = mode;
    this._saveMemory();
  }

  // Voice
  isRecording = false;
  recordingTime = 0;
  audioBlob: Blob | null = null;
  micAvailable = true;
  private mediaRecorder: MediaRecorder | null = null;
  private audioChunks: Blob[] = [];
  private recordingTimer: any = null;

  // Telegram relay
  telegramText = '';

  onTelegramChange() {
    this._saveMemory();
  }

  // ── Step 3 — Swarm processing ─────────────────────────────────────────
  processing = false;
  processingState: string = '';
  processingProgress = 0;
  sessionId: string | null = null;
  pipelineLog: { state: string; label: string; done: boolean }[] = [];

  // ── Step 4 — Result ───────────────────────────────────────────────────
  extractionResult: ExtractionResult | null = null;
  clarificationText = '';
  clarifying = false;
  gateSession: any = null;

  // ── GPS / Location ─────────────────────────────────────────────────────
  gpsLat: number = 0;
  gpsLng: number = 0;
  gpsAccuracy: number | null = null;
  gpsStatus: 'idle' | 'requesting' | 'acquired' | 'denied' | 'unavailable' =
    'idle';
  gpsAddress: string = ''; // reverse-geocoded human label (best-effort)

  private destroy$ = new Subject<void>();

  constructor(
    private fb: FormBuilder,
    private intakeAgent: IntakeAgentService,
    private rootAgent: RootAgentService,
    private api: ApiService,
    private snack: MatSnackBar,
    private cd: ChangeDetectorRef,
    private router: Router,
  ) {}

  ngOnInit() {
    this._buildForms();
    this._loadMemory();
    this._setupMemorySync();
    this._setupAudioRecording();
    this._subscribeToSessionUpdates();
    this._requestGps(); // request immediately so location is ready by the time pipeline runs
  }

  ngOnDestroy() {
    this.stopRecording();
    this.destroy$.next();
    this.destroy$.complete();
  }

  // ── Form builders ──────────────────────────────────────────────────────

  private _buildForms() {
    this.identityForm = this.fb.group({
      role: [null, Validators.required],
      chw_id: ['', Validators.required],
      name: ['', [Validators.required, Validators.minLength(2)]],
      county: ['', Validators.required],
    });

    this.patientForm = this.fb.group({
      chief_complaint: ['', Validators.required],
      age_value: [null],
      age_unit: ['years'],
      sex: [''],
      county: [''],
      temperature_c: [null],
      respiratory_rate: [null],
      heart_rate: [null],
      duration_days: [null],
      syndrome_hint: [''],
      language_hint: [''],
      patient_contacts: [''],
    });
  }

  // ── Web Memory ─────────────────────────────────────────────────────────

  private _saveMemory() {
    if (typeof localStorage === 'undefined') return;
    const mem = {
      identityForm: this.identityForm.value,
      role: this.role,
      identityVerified: this.identityVerified,
      patientForm: this.patientForm.value,
      symptoms: this.symptoms,
      intakeMode: this.intakeMode,
      telegramText: this.telegramText,
    };
    localStorage.setItem('siha_intake_memory', JSON.stringify(mem));
  }

  private _loadMemory() {
    if (typeof localStorage === 'undefined') return;
    const stored = localStorage.getItem('siha_intake_memory');
    if (!stored) return;
    try {
      const mem = JSON.parse(stored);
      if (mem.identityForm)
        this.identityForm.patchValue(mem.identityForm, { emitEvent: false });
      if (mem.role) {
        this.role = mem.role as UserRole;
        // setRole logic
        if (this.role === 'clinician') {
          this.identityForm
            .get('chw_id')
            ?.setValidators([
              Validators.required,
              Validators.pattern(/^(CHW|DOC|NRS|CL)-[A-Z0-9]+$/i),
            ]);
        }
        this.identityForm
          .get('chw_id')
          ?.updateValueAndValidity({ emitEvent: false });
      }
      if (mem.identityVerified) this.identityVerified = mem.identityVerified;
      if (mem.patientForm)
        this.patientForm.patchValue(mem.patientForm, { emitEvent: false });
      if (mem.symptoms) this.symptoms = mem.symptoms;
      if (mem.intakeMode) this.intakeMode = mem.intakeMode;
      if (mem.telegramText) this.telegramText = mem.telegramText;

      // Auto-advance stepper to Step 1 if identity was already verified
      if (this.identityVerified) {
        setTimeout(() => this.stepper?.next(), 300);
      }
    } catch (e) {
      console.warn('Failed to parse intake memory', e);
    }
  }

  private _setupMemorySync() {
    this.identityForm.valueChanges
      .pipe(takeUntil(this.destroy$))
      .subscribe(() => this._saveMemory());
    this.patientForm.valueChanges
      .pipe(takeUntil(this.destroy$))
      .subscribe(() => this._saveMemory());
  }

  // ── Step 0 — Identity verification ────────────────────────────────────

  setRole(r: UserRole) {
    this.role = r;
    this.identityForm.patchValue({ role: r });
    // Pre-fill county label based on role
    if (r === 'clinician') {
      this.identityForm
        .get('chw_id')
        ?.setValidators([
          Validators.required,
          Validators.pattern(/^(CHW|DOC|NRS|CL)-[A-Z0-9]+$/i),
        ]);
    }
    this.identityForm.get('chw_id')?.updateValueAndValidity();
    this._saveMemory();
  }

  async verifyIdentity() {
    if (this.identityForm.invalid) {
      this.identityForm.markAllAsTouched();
      return;
    }
    this.verifying = true;
    try {
      const { chw_id, name, county, role } = this.identityForm.value;
      // Register/verify CHW in MongoDB via the data agent
      await this.api.post('/tool/register_chw', {
        chw_id,
        name,
        county,
        role: role ?? 'chw',
        status: 'active',
        source: 'web_intake',
      });
      this.identityVerified = true;
      // Pre-fill patient county from operator county
      this.patientForm.patchValue({ county });
      this._saveMemory();
      setTimeout(() => this.stepper?.next(), 300);
    } catch (err) {
      // If the CHW doesn't exist yet, still allow access (they'll be created)
      this.identityVerified = true;
      this.patientForm.patchValue({ county: this.identityForm.value.county });
      setTimeout(() => this.stepper?.next(), 300);
    } finally {
      this.verifying = false;
    }
  }

  get operatorLabel(): string {
    const n = this.identityForm.value.name;
    const id = this.identityForm.value.chw_id;
    return n && id ? `${n} (${id})` : '';
  }

  // ── Step 1 — Symptoms ──────────────────────────────────────────────────

  addSymptom() {
    const s = this.symptomInput.trim();
    if (s && !this.symptoms.includes(s)) {
      this.symptoms = [...this.symptoms, s];
      this._saveMemory();
    }
    this.symptomInput = '';
  }

  removeSymptom(s: string) {
    this.symptoms = this.symptoms.filter((x) => x !== s);
    this._saveMemory();
  }

  advanceToIntake() {
    if (
      this.patientForm.get('chief_complaint')?.invalid &&
      this.symptoms.length === 0
    ) {
      this.snack.open('Enter a chief complaint or at least one symptom', 'OK', {
        duration: 3000,
      });
      return;
    }
    this.stepper?.next();
  }

  // ── Audio recording ────────────────────────────────────────────────────

  private async _setupAudioRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm';
      this.mediaRecorder = new MediaRecorder(stream, { mimeType: mime });
      this.mediaRecorder.ondataavailable = (e: BlobEvent) => {
        if (e.data.size > 0) this.audioChunks.push(e.data);
      };
      this.mediaRecorder.onstop = () => {
        this.audioBlob = new Blob(this.audioChunks, {
          type: this.mediaRecorder!.mimeType,
        });
        this.audioChunks = [];
        this.cd.markForCheck();
      };
    } catch {
      this.micAvailable = false;
    }
  }

  startRecording() {
    if (!this.mediaRecorder) {
      this.snack.open('Microphone unavailable — check permissions', 'OK', {
        duration: 4000,
      });
      return;
    }
    this.audioChunks = [];
    this.audioBlob = null;
    this.mediaRecorder.start(250);
    this.isRecording = true;
    this.recordingTime = 0;
    this.recordingTimer = setInterval(() => {
      this.recordingTime++;
      this.cd.markForCheck();
    }, 1000);
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

  get recordingDisplay(): string {
    const m = Math.floor(this.recordingTime / 60);
    const s = this.recordingTime % 60;
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  private _blobToBase64(blob: Blob): Promise<string> {
    return new Promise((res, rej) => {
      const r = new FileReader();
      r.onloadend = () => res((r.result as string).split(',')[1] ?? '');
      r.onerror = rej;
      r.readAsDataURL(blob);
    });
  }

  // ── GPS capture ────────────────────────────────────────────────────────

  /** Request browser geolocation. Called on init and on user tap of the location button. */
  requestGps() {
    this._requestGps();
  }

  private _requestGps() {
    if (!navigator.geolocation) {
      this.gpsStatus = 'unavailable';
      return;
    }
    this.gpsStatus = 'requesting';
    this.cd.markForCheck();

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        this.gpsLat = pos.coords.latitude;
        this.gpsLng = pos.coords.longitude;
        this.gpsAccuracy = pos.coords.accuracy;
        this.gpsStatus = 'acquired';
        this._reverseGeocode(this.gpsLat, this.gpsLng);
        this.cd.markForCheck();
      },
      (err) => {
        this.gpsStatus = err.code === 1 ? 'denied' : 'unavailable';
        this.cd.markForCheck();
      },
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 60000 },
    );
  }

  /** Best-effort reverse geocode using the Geo Agent endpoint (no extra key needed). */
  private async _reverseGeocode(lat: number, lng: number) {
    try {
      const res: any = await this.api.post('/tool/get_admin_hierarchy', {
        lat,
        lng,
      });
      const h = res?.admin_hierarchy;
      if (h) {
        const parts = [h.ward, h.sub_county, h.county].filter(Boolean);
        this.gpsAddress = parts.join(', ');
        // Pre-fill county on the patient form if it's empty
        if (h.county && !this.patientForm.get('county')?.value) {
          this.patientForm.patchValue({ county: h.county });
        }
        this.cd.markForCheck();
      }
    } catch {
      // non-fatal — address label is optional
    }
  }

  get gpsLabel(): string {
    switch (this.gpsStatus) {
      case 'requesting':
        return 'Acquiring location…';
      case 'acquired':
        return (
          this.gpsAddress ||
          `${this.gpsLat.toFixed(5)}, ${this.gpsLng.toFixed(5)}`
        );
      case 'denied':
        return 'Location access denied';
      case 'unavailable':
        return 'GPS unavailable';
      default:
        return 'Location not captured';
    }
  }

  get gpsIcon(): string {
    switch (this.gpsStatus) {
      case 'requesting':
        return 'my_location';
      case 'acquired':
        return 'location_on';
      case 'denied':
        return 'location_off';
      case 'unavailable':
        return 'location_disabled';
      default:
        return 'location_searching';
    }
  }

  // ── Step 2 → 3: Start encounter pipeline ──────────────────────────────

  async launchPipeline() {
    this.processing = true;
    this.extractionResult = null;
    this.sessionId = `web-${this.identityForm.value.chw_id}-${Date.now()}`;

    this._initPipelineLog();

    const { chw_id, county: opCounty } = this.identityForm.value;
    const patient = this.patientForm.value;

    let audio_base64 = '';
    let form_data: any = null;
    let telegram_payload: any = null;

    try {
      if (this.intakeMode === 'voice' && this.audioBlob) {
        audio_base64 = await this._blobToBase64(this.audioBlob);
      } else if (this.intakeMode === 'form') {
        form_data = {
          chief_complaint: patient.chief_complaint,
          symptoms: this.symptoms,
          age_value: patient.age_value,
          age_unit: patient.age_unit,
          sex: patient.sex,
          temperature_c: patient.temperature_c,
          respiratory_rate: patient.respiratory_rate,
          heart_rate: patient.heart_rate,
          duration_days: patient.duration_days,
          syndrome_hint: patient.syndrome_hint,
          language_hint: patient.language_hint,
          county: patient.county || opCounty,
          patient_contacts: patient.patient_contacts,
        };
      } else if (this.intakeMode === 'telegram') {
        telegram_payload = {
          chw_id,
          message_text: this.telegramText,
          language_hint: patient.language_hint,
        };
      }
    } catch (encodeErr) {
      this.processing = false;
      this.snack.open('Failed to encode audio', 'Dismiss', { duration: 4000 });
      return;
    }

    // Move to step 3 so user sees the pipeline
    this.stepper?.next();

    // Fire the pipeline as a non-blocking background task.
    // The subscription in _subscribeToSessionUpdates drives all state
    // transitions (DECISION_GATE, COMPLETE, FAILED) via sessionUpdates$.
    // We only use the returned promise to catch a fatal startup error.
    this.rootAgent
      .startEncounter({
        audio_base64,
        latitude: this.gpsLat,
        longitude: this.gpsLng,
        chw_id,
        sessionId: this.sessionId!,
        form_data,
        telegram_payload,
      })
      .then((session) => {
        // Pipeline finished — grab final extraction if subscription missed it
        if (!this.extractionResult && session.data?.extraction) {
          this.extractionResult = this._normalizeResult(
            session.data.extraction as ExtractionResult,
          );
          this._markAllPipelineDone();
        }
        // Only set gateSession from here if subscription didn't already catch it
        if (session.state === 'DECISION_GATE' && !this.gateSession) {
          this.gateSession = session;
        }
        this.processing = false;
        this.cd.detectChanges();
        // Advance to results step if not already there
        if (this.extractionResult) {
          setTimeout(() => {
            this.stepper?.next();
            this.cd.detectChanges();
          }, 200);
        }
      })
      .catch((err) => {
        this.processing = false;
        this.snack.open(
          err instanceof Error ? err.message : 'Pipeline failed',
          'Dismiss',
          { duration: 6000 },
        );
        this.cd.detectChanges();
      });
  }

  private _initPipelineLog() {
    this.pipelineLog = [
      {
        state: 'EXTRACTING',
        label: 'Clinical Extraction (Gemini)',
        done: false,
      },
      {
        state: 'GEOCODING',
        label: 'Geo Enrichment (Google Maps)',
        done: false,
      },
      { state: 'STORING', label: 'Data Persistence (Atlas)', done: false },
      { state: 'ALERTING', label: 'Referral Record Created', done: false },
      { state: 'NOTIFYING', label: 'Telegram Dispatch', done: false },
    ];
  }

  private _markAllPipelineDone() {
    this.pipelineLog.forEach((s) => (s.done = true));
  }

  // ── Session state polling → pipeline log ──────────────────────────────

  private _subscribeToSessionUpdates() {
    this.rootAgent.sessionUpdates$
      .pipe(takeUntil(this.destroy$))
      .subscribe((session) => {
        if (!session || session.sessionId !== this.sessionId) return;
        this.processingState = session.state;

        // Mark pipeline steps done as state progresses
        const ORDER = [
          'EXTRACTING',
          'GEOCODING',
          'STORING',
          'ALERTING',
          'NOTIFYING',
          'COMPLETE',
        ];
        const idx = ORDER.indexOf(session.state);
        this.pipelineLog.forEach((step, i) => {
          if (i < idx) step.done = true;
        });
        this.processingProgress =
          idx >= 0 ? Math.round((idx / (ORDER.length - 1)) * 100) : 0;

        if (session.state === 'DECISION_GATE') this.gateSession = session;

        // Populate result as soon as extraction data arrives — don't wait for COMPLETE
        if (session.data?.extraction && !this.extractionResult) {
          this.extractionResult = this._normalizeResult(
            session.data.extraction as ExtractionResult,
          );
          this._markAllPipelineDone();
          // Auto-advance stepper to the Result step
          setTimeout(() => {
            this.stepper?.next();
            this.cd.detectChanges();
          }, 200);
        }

        this.cd.markForCheck();
      });
  }

  // ── Step 4 — Gate and clarification ───────────────────────────────────

  async confirmGate(confirmed: boolean) {
    if (!this.gateSession) return;
    const sessionId = this.gateSession.sessionId;
    this.gateSession = null; // close immediately — don't wait for the async call

    try {
      const { resolved, timedOut } =
        await this.rootAgent.confirmEncounterDecision(sessionId, confirmed);

      if (timedOut) {
        // Gate already expired — backend auto-handled it
        this.snack.open(
          '⏱️ Gate timed out — the encounter was auto-processed. Check Case Encounters.',
          'OK',
          { duration: 7000 },
        );
      } else if (confirmed) {
        this.snack.open('✅ Referral dispatched to facility', 'OK', {
          duration: 5000,
        });
      } else {
        this.snack.open('❌ Referral declined — encounter logged', 'OK', {
          duration: 5000,
        });
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error('Gate confirmation error:', msg);
      this.snack.open(
        `Gate confirmation failed: ${msg.slice(0, 80)}`,
        'Dismiss',
        { duration: 6000 },
      );
    }
  }

  async submitClarification() {
    if (!this.clarificationText.trim() || !this.extractionResult) return;
    this.clarifying = true;
    try {
      this.extractionResult = await this.intakeAgent.clarifyExtraction({
        original_extraction: this.extractionResult,
        clarification_answer: this.clarificationText.trim(),
      });
      this.clarificationText = '';
    } catch (err) {
      this.snack.open(
        err instanceof Error ? err.message : 'Clarification failed',
        'Dismiss',
        { duration: 4000 },
      );
    } finally {
      this.clarifying = false;
    }
  }

  // ── Full reset ─────────────────────────────────────────────────────────

  reset() {
    this.identityVerified = false;
    this.role = null;
    this.extractionResult = null;
    this.gateSession = null;
    this.sessionId = null;
    this.processing = false;
    this.pipelineLog = [];
    this.audioBlob = null;
    this.recordingTime = 0;
    this.symptoms = [];
    this.telegramText = '';
    this.clarificationText = '';
    this.identityForm.reset();
    this.patientForm.reset({ age_unit: 'years' });

    if (typeof localStorage !== 'undefined') {
      localStorage.removeItem('siha_intake_memory');
    }

    setTimeout(() => this.stepper?.reset(), 100);
  }

  /** Navigate to Case Encounters — where all logged intake cases are visible. */
  goToEncounters() {
    this.router.navigate(['/encounters']);
  }

  // ── Helpers ────────────────────────────────────────────────────────────

  /** Ensure all array/object fields are present so the template never calls .length on undefined */
  private _normalizeResult(raw: any): ExtractionResult {
    return {
      ...raw,
      symptoms: Array.isArray(raw?.symptoms)
        ? raw.symptoms
        : Array.isArray(raw?.primary_symptoms)
          ? raw.primary_symptoms
          : [],
      recommended_actions: Array.isArray(raw?.recommended_actions)
        ? raw.recommended_actions
        : [],
      clarification_questions: Array.isArray(raw?.clarification_questions)
        ? raw.clarification_questions
        : [],
      vitals: raw?.vitals ?? raw?.vital_signs ?? {},
      confidence_score: raw?.confidence_score ?? raw?.confidence ?? 0,
    };
  }

  triageColor(t?: string): string {
    switch (t) {
      case 'RED':
        return '#d32f2f';
      case 'YELLOW':
        return '#f59e0b';
      case 'GREEN':
        return '#16a34a';
      default:
        return '#757575';
    }
  }
  triageIcon(t?: string): string {
    switch (t) {
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
  formatSyndrome(s?: string): string {
    return (s ?? 'unknown').replace(/_/g, ' ');
  }

  canLaunch(): boolean {
    if (this.intakeMode === 'voice')
      return !!this.audioBlob && !this.isRecording;
    if (this.intakeMode === 'form')
      return (
        !!this.patientForm.get('chief_complaint')?.value?.trim() ||
        this.symptoms.length > 0
      );
    if (this.intakeMode === 'telegram') return !!this.telegramText.trim();
    return false;
  }
}
