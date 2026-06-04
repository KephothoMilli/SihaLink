/**
 * Data Agent UI Component
 *
 * Search encounters, view follow-ups, and check county stats.
 */

import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import {
  DataAgentService,
  StoredEncounter,
} from '../../../services/agents/data-agent.service';

@Component({
  selector: 'app-data-agent',
  templateUrl: './data-agent.component.html',
  styleUrl: './data-agent.component.css',
  standalone: true,
  imports: [CommonModule, FormsModule],
})
export class DataAgentComponent implements OnInit {
  searchQuery = '';
  searchResults: any = null;
  isLoading = false;
  error: string | null = null;
  selectedEncounter: StoredEncounter | null = null;

  // County stats (replaces the removed getTrendAnalysis)
  countyStats: any = null;
  showStats = false;
  statsCounty = '';

  constructor(private dataAgent: DataAgentService) {}

  ngOnInit() {}

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

  selectEncounter(encounter: StoredEncounter) {
    this.selectedEncounter = encounter;
  }

  async getCountyStats() {
    if (!this.statsCounty.trim()) {
      this.error = 'Please enter a county name';
      return;
    }
    this.isLoading = true;
    this.error = null;
    try {
      this.countyStats = await this.dataAgent.getCountyStats(this.statsCounty);
      this.showStats = true;
    } catch (err) {
      this.error =
        err instanceof Error ? err.message : 'Failed to get county stats';
    } finally {
      this.isLoading = false;
    }
  }

  clearSelection() {
    this.selectedEncounter = null;
  }

  clearStats() {
    this.showStats = false;
    this.countyStats = null;
  }
}
