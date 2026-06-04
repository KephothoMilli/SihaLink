/**
 * Data Agent UI Component
 * 
 * Interface for searching and managing stored encounters
 */

import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { DataAgentService, StoredEncounter, SearchResult } from '../../../services/agents/data-agent.service';

@Component({
    selector: 'app-data-agent',
    templateUrl: './data-agent.component.html',
    styleUrl: './data-agent.component.css',
    standalone: true,
    imports: [CommonModule, FormsModule],
})
export class DataAgentComponent implements OnInit {
    searchQuery: string = '';
    searchResults: SearchResult | null = null;
    isLoading = false;
    error: string | null = null;
    selectedEncounter: StoredEncounter | null = null;

    trendData: any = null;
    showTrends = false;
    trendRegion: string = '';
    trendDays: number = 30;

    constructor(private dataAgent: DataAgentService) { }

    ngOnInit() { }

    async searchEncounters() {
        if (!this.searchQuery.trim()) {
            this.error = 'Please enter a search query';
            return;
        }

        this.isLoading = true;
        this.error = null;

        try {
            this.searchResults = await this.dataAgent.searchEncounters({
                query: this.searchQuery,
                limit: 20,
            });
        } catch (err) {
            this.error = err instanceof Error ? err.message : 'Search failed';
        } finally {
            this.isLoading = false;
        }
    }

    async selectEncounter(encounter: StoredEncounter) {
        this.selectedEncounter = encounter;
    }

    async getTrendAnalysis() {
        this.isLoading = true;
        this.error = null;

        try {
            this.trendData = await this.dataAgent.getTrendAnalysis({
                region: this.trendRegion,
                time_range_days: this.trendDays,
            });
            this.showTrends = true;
        } catch (err) {
            this.error = err instanceof Error ? err.message : 'Failed to get trends';
        } finally {
            this.isLoading = false;
        }
    }

    clearSelection() {
        this.selectedEncounter = null;
    }

    clearTrends() {
        this.showTrends = false;
        this.trendData = null;
    }
}
