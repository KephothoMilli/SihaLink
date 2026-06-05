/**
 * Intake Agent Service
 *
 * Three intake paths — all route through the orchestrator backend:
 *   1. extractClinicalData()    → POST /tool/route_to_intake  (audio base64)
 *   2. submitForm()             → POST /intake/form           (structured form)
 *   3. relayTelegramMessage()   → POST /intake/telegram       (CHV text/message relay)
 */

import { Injectable } from '@angular/core';
import { ApiService } from '../api.service';

export interface ExtractionRequest {
  audio_base64: string;
  clarification_answers?: string[];
}

export interface FormIntakeRequest {
  chief_complaint: string;
  symptoms?: string[];
  age_value?: number;
  age_unit?: 'years' | 'months' | 'weeks' | 'days';
  sex?: string;
  temperature_c?: number;
  respiratory_rate?: number;
  heart_rate?: number;
  duration_days?: number;
  syndrome_hint?: string;
  language_hint?: string;
  county?: string;
  patient_contacts?: string;
}

export interface TelegramIntakeRequest {
  chw_id: string;
  message_text: string;
  audio_base64?: string;
  language_hint?: string;
}

export interface ExtractionResult {
  symptoms: string[];
  vitals: {
    temperature?: number;
    blood_pressure?: string;
    heart_rate?: number;
    respiratory_rate?: number;
  };
  clinical_assessment: string;
  recommended_actions: string[];
  clarification_questions: string[];
  confidence_score: number;
  // extra fields the backend may return
  [key: string]: any;
}

@Injectable({ providedIn: 'root' })
export class IntakeAgentService {
  constructor(private api: ApiService) {}

  /** Extract clinical data from base64 audio (Gemini Live API). */
  async extractClinicalData(
    request: ExtractionRequest,
  ): Promise<ExtractionResult> {
    const res: any = await this.api.extractClinicalData(request);
    // Backend wraps in { session_id, extracted } — unwrap if needed
    return res?.extracted ?? res;
  }

  /**
   * Submit a structured web form to the intake pipeline.
   * Calls POST /intake/form on the orchestrator.
   */
  async submitForm(request: FormIntakeRequest): Promise<ExtractionResult> {
    const res: any = await this.api.intakeForm(request);
    return res?.extracted ?? res;
  }

  /**
   * Relay a CHV Telegram message through the intake pipeline.
   * Calls POST /intake/telegram on the orchestrator.
   */
  async relayTelegramMessage(
    request: TelegramIntakeRequest,
  ): Promise<ExtractionResult> {
    const res: any = await this.api.intakeTelegram(request);
    return res?.extracted ?? res;
  }

  /** Refine a previous extraction with a CHV clarification answer. */
  async clarifyExtraction(request: {
    original_extraction: ExtractionResult;
    clarification_answer: string;
  }): Promise<ExtractionResult> {
    const res: any = await this.api.clarifyExtraction(request);
    return res?.extracted ?? res;
  }

  /** Confirm or decline an encounter at the human-in-the-loop gate. */
  async confirmDecision(sessionId: string, confirmed: boolean): Promise<void> {
    return this.api.confirmEncounter(sessionId, confirmed);
  }

  async healthCheck(): Promise<boolean> {
    try {
      await this.api.healthIntake();
      return true;
    } catch {
      return false;
    }
  }
}
