/**
 * Notify Agent Service
 *
 * Sends alerts and notifications through Telegram and other channels.
 * Manages notification routing to appropriate health workers and supervisors.
 */

import { Injectable } from '@angular/core';
import { ApiService } from '../api.service';

export interface NotificationPayload {
  title: string;
  message: string;
  recipients: string[]; // Telegram chat IDs or phone numbers
  encounter_id?: string;
  priority?: 'low' | 'medium' | 'high' | 'critical';
  action_url?: string;
  metadata?: any;
}

export interface NotificationResult {
  notification_id: string;
  sent_at: number; // milliseconds since epoch (for Angular date pipe)
  sent_at_iso?: string; // ISO 8601 string with timezone (preferred)
  recipients_reached: number;
  failed_recipients: string[];
  status: 'sent' | 'partial' | 'failed';
}

@Injectable({
  providedIn: 'root',
})
export class NotifyAgentService {
  constructor(private api: ApiService) {}

  /**
   * Send a notification to recipients
   */
  async sendNotification(
    request: NotificationPayload,
  ): Promise<NotificationResult> {
    return this.api.sendNotification(request);
  }

  /**
   * Send an urgent alert (automatically sets priority to critical)
   */
  async sendUrgentAlert(request: {
    title: string;
    message: string;
    recipients: string[];
    encounter_id?: string;
  }): Promise<NotificationResult> {
    return this.sendNotification({
      ...request,
      priority: 'critical',
    });
  }

  /**
   * Get notification history for an encounter
   */
  async getNotificationHistory(
    encounterId: string,
  ): Promise<NotificationResult[]> {
    return this.api.getNotificationHistory(encounterId);
  }

  /**
   * Get delivery status of a notification
   */
  async getNotificationStatus(
    notificationId: string,
  ): Promise<NotificationResult> {
    return this.api.getNotificationStatus(notificationId);
  }

  /**
   * Register a recipient (CHW, supervisor, etc.)
   */
  async registerRecipient(request: {
    telegram_id?: string;
    phone_number?: string;
    name: string;
    role: string;
  }): Promise<{ recipient_id: string }> {
    return this.api.registerRecipient(request);
  }

  /**
   * Get list of registered recipients
   */
  async getRecipients(): Promise<any[]> {
    return this.api.getRecipients();
  }

  /**
   * Check if Notify Agent is available
   */
  async healthCheck(): Promise<boolean> {
    try {
      await this.api.healthNotify();
      return true;
    } catch {
      return false;
    }
  }
}
