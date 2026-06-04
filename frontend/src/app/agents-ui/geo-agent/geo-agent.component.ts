import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import {
  GeoAgentService,
  Location,
  Facility,
} from '../../../services/agents/geo-agent.service';

@Component({
  selector: 'app-geo-agent',
  templateUrl: './geo-agent.component.html',
  styleUrl: './geo-agent.component.css',
  standalone: true,
  imports: [CommonModule, FormsModule],
})
export class GeoAgentComponent implements OnInit {
  latitude = -1.3521;
  longitude = 36.8155;
  radius_km = 50;

  facilities: Facility[] = [];
  adminHierarchy: any = null;
  isLoading = false;
  error: string | null = null;
  selectedFacility: Facility | null = null;

  constructor(private geoAgent: GeoAgentService) {}

  ngOnInit() {
    this.getCurrentLocation();
  }

  getCurrentLocation() {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        this.latitude = pos.coords.latitude;
        this.longitude = pos.coords.longitude;
      },
      () => {}, // keep defaults on error
    );
  }

  async findNearestFacilities() {
    this.isLoading = true;
    this.error = null;
    try {
      this.facilities = await this.geoAgent.findNearestFacilities(
        { latitude: this.latitude, longitude: this.longitude },
        this.radius_km,
      );
    } catch (err) {
      this.error =
        err instanceof Error ? err.message : 'Failed to find facilities';
    } finally {
      this.isLoading = false;
    }
  }

  async getAdminHierarchy() {
    this.isLoading = true;
    this.error = null;
    try {
      this.adminHierarchy = await this.geoAgent.getAdminHierarchy({
        latitude: this.latitude,
        longitude: this.longitude,
      });
    } catch (err) {
      this.error =
        err instanceof Error ? err.message : 'Failed to get admin hierarchy';
    } finally {
      this.isLoading = false;
    }
  }

  async selectFacility(facility: Facility) {
    this.selectedFacility = facility;
    this.isLoading = true;
    this.error = null;
    try {
      const eta = await this.geoAgent.getETAToFacility(
        { latitude: this.latitude, longitude: this.longitude },
        { latitude: 0, longitude: 0 },
      );
      facility.eta_minutes = eta.eta_minutes;
      facility.distance_km = eta.distance_km;
    } catch (err) {
      this.error =
        err instanceof Error ? err.message : 'Failed to calculate ETA';
    } finally {
      this.isLoading = false;
    }
  }

  clearSelection() {
    this.selectedFacility = null;
  }
}
