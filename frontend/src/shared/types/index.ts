/**
 * Shared TypeScript types for SihaLink
 * Used by the Notify Agent (grammY bot) and frontend.
 */

export interface Age {
  value: number;
  unit: 'days' | 'months' | 'years';
}

export interface ExtractedClinicalData {
  language: string;
  syndrome: string;
  primary_symptoms: string[];
  severity: 'mild' | 'moderate' | 'severe';
  triage_color: 'GREEN' | 'YELLOW' | 'RED';
  chief_complaint: string;
  age?: Age;
  sex?: 'male' | 'female' | 'unknown';
  confidence: number;
}

export interface AdminHierarchy {
  village: string;
  ward: string;
  sub_county: string;
  county: string;
}

export interface Facility {
  place_id: string;
  name: string;
  address: string;
  distance_km: number;
  eta_minutes: number;
  open_now: boolean;
  has_emergency: boolean;
}

export interface GeoPoint {
  type: 'Point';
  coordinates: [number, number]; // [lng, lat]
}

export interface Encounter {
  session_id: string;
  encounter_id?: string;
  timestamp?: string;
  extracted: ExtractedClinicalData;
  location: GeoPoint;
  admin_hierarchy: AdminHierarchy;
  nearest_facilities: Facility[];
  location_confidence: 'high' | 'low';
  embedding?: number[];
  synced: boolean;
}

export interface ReferralData {
  encounter_id: string;
  referral_id?: string;
  syndrome: string;
  triage_color: 'RED' | 'YELLOW' | 'GREEN';
  eta_minutes: number;
  facility_telegram_id: string | number;
  nearest_facility?: string;
  age?: Age;
  sex?: string;
  chief_complaint?: string;
}

export interface AlertDocument {
  alert_id: string;
  encounter_id?: string;
  syndrome: string;
  triage_color?: 'RED' | 'YELLOW';
  location: {
    county: string;
    ward: string;
    coordinates?: [number, number];
  };
  count: number;
  baseline?: number;
  percent_above_baseline: number;
  encounter_ids?: string[];
  detected_at: string;
  status: 'active' | 'acknowledged' | 'resolved';
  priority?: 'HIGH' | 'MEDIUM' | 'LOW';
  correlation_type?: string;
  contributing_syndromes?: string[];
}

export interface OfflineQueueItem {
  session_id: string;
  audio_base64: string;
  coords: { lat: number; lng: number };
  queued_at: string;
  synced: boolean;
}
