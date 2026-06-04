/**
 * Notify Agent UI Component
 * 
 * Interface for sending alerts and notifications
 */

import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { NotifyAgentService, NotificationResult } from '../../../services/agents/notify-agent.service';

@Component({
    selector: 'app-notify-agent',
    templateUrl: './notify-agent.component.html',
    styleUrl: './notify-agent.component.css',
    standalone: true,
    imports: [CommonModule, FormsModule],
})
export class NotifyAgentComponent implements OnInit {
    notificationTitle: string = '';
    notificationMessage: string = '';
    recipients: string = '';
    priority: 'low' | 'medium' | 'high' | 'critical' = 'medium';
    encounterId: string = '';

    notificationResult: NotificationResult | null = null;
    isLoading = false;
    error: string | null = null;

    registeredRecipients: any[] = [];
    showRegistration = false;
    newRecipientName: string = '';
    newRecipientRole: string = '';
    newRecipientTelegramId: string = '';
    newRecipientPhone: string = '';

    constructor(private notifyAgent: NotifyAgentService) { }

    ngOnInit() {
        this.loadRecipients();
    }

    async loadRecipients() {
        try {
            this.registeredRecipients = await this.notifyAgent.getRecipients();
        } catch (err) {
            console.error('Failed to load recipients:', err);
        }
    }

    async sendNotification() {
        if (!this.notificationTitle.trim() || !this.notificationMessage.trim() || !this.recipients.trim()) {
            this.error = 'Please fill in all required fields';
            return;
        }

        this.isLoading = true;
        this.error = null;

        try {
            const recipientList = this.recipients
                .split(',')
                .map((r) => r.trim())
                .filter((r) => r.length > 0);

            this.notificationResult = await this.notifyAgent.sendNotification({
                title: this.notificationTitle,
                message: this.notificationMessage,
                recipients: recipientList,
                priority: this.priority,
                encounter_id: this.encounterId || undefined,
            });
        } catch (err) {
            this.error = err instanceof Error ? err.message : 'Failed to send notification';
        } finally {
            this.isLoading = false;
        }
    }

    async registerRecipient() {
        if (!this.newRecipientName.trim() || !this.newRecipientRole.trim()) {
            this.error = 'Please fill in name and role';
            return;
        }

        this.isLoading = true;
        this.error = null;

        try {
            await this.notifyAgent.registerRecipient({
                name: this.newRecipientName,
                role: this.newRecipientRole,
                telegram_id: this.newRecipientTelegramId || undefined,
                phone_number: this.newRecipientPhone || undefined,
            });

            // Clear form and reload recipients
            this.newRecipientName = '';
            this.newRecipientRole = '';
            this.newRecipientTelegramId = '';
            this.newRecipientPhone = '';
            this.showRegistration = false;

            await this.loadRecipients();
        } catch (err) {
            this.error = err instanceof Error ? err.message : 'Failed to register recipient';
        } finally {
            this.isLoading = false;
        }
    }

    clearResults() {
        this.notificationResult = null;
    }

    getPriorityColor(priority: string): string {
        switch (priority) {
            case 'critical':
                return 'red';
            case 'high':
                return 'orange';
            case 'medium':
                return 'yellow';
            default:
                return 'green';
        }
    }
}
