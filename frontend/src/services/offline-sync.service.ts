/**
 * OfflineSyncService
 * Stores encounters in localStorage when the device is offline.
 * The AppComponent triggers sync when connectivity returns.
 */

import { Injectable } from '@angular/core';

const QUEUE_KEY = 'afya_offline_queue';

export interface QueuedEncounter {
  session_id: string;
  audio_base64: string;
  latitude: number;
  longitude: number;
  queued_at: string;
}

@Injectable({ providedIn: 'root' })
export class OfflineSyncService {
  queueEncounter(encounter: Omit<QueuedEncounter, 'queued_at'>) {
    const queue = this.getQueue();
    queue.push({ ...encounter, queued_at: new Date().toISOString() });
    localStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
  }

  getQueue(): QueuedEncounter[] {
    try {
      return JSON.parse(localStorage.getItem(QUEUE_KEY) || '[]');
    } catch {
      return [];
    }
  }

  getQueueSize(): number {
    return this.getQueue().length;
  }

  clearQueue() {
    localStorage.removeItem(QUEUE_KEY);
  }

  /** Remove a specific encounter from the queue by session_id. */
  removeFromQueue(encounter: QueuedEncounter | { session_id: string }) {
    const queue = this.getQueue().filter(
      (e) => e.session_id !== encounter.session_id,
    );
    localStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
  }

  /** @deprecated Use removeFromQueue instead */
  removeItem(sessionId: string) {
    const queue = this.getQueue().filter((e) => e.session_id !== sessionId);
    localStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
  }
}
