/**
 * Intake Agent Service
 * 
 * Handles clinical data extraction from audio using Gemini Live API.
 * Extracts symptoms, vitals, and clinical information from CHV audio recordings.
 */

import { Injectable } from '@angular/core';
import { ApiService } from '../api.service';

export interface ExtractionRequest {
    audio_base64: string;
    clarification_answers?: string[];
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
    clarification_questions?: string[];
    confidence_score: number;
}

@Injectable({
    providedIn: 'root'
})
export class IntakeAgentService {
    constructor(private api: ApiService) { }

    /**
    * Extract clinical data from base64 audio
    */
    async extractClinicalData(request: ExtractionRequest): Promise<ExtractionResult> {
        return this.api.extractClinicalData(request);
    }

    /**
    * Refine a previous extraction with clarification from CHV
    */
    async clarifyExtraction(request: {
        original_extraction: ExtractionResult;
        clarification_answer: string;
    }): Promise<ExtractionResult> {
        return this.api.clarifyExtraction(request);
    }

    /**
    * Confirm a clinical extraction (for human-in-the-loop validation)
    */
    async confirmDecision(sessionId: string, confirmed: boolean): Promise<void> {
        return this.api.confirmEncounter(sessionId, confirmed);
    }

    /**
    * Check if Intake Agent is available
    */
    async healthCheck(): Promise<boolean> {
        try {
            return await this.api.healthIntake();
        } catch {
            return false;
        }
    }
}
