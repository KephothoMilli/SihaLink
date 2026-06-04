import googlemaps
import os
from datetime import datetime
from typing import Dict, List, Any

class GeoAgent:
    def __init__(self):
        self.gmaps = googlemaps.Client(key=os.getenv("GOOGLE_MAPS_API_KEY"))

    async def enrich_location(self, encounter_json: Dict, coords: Dict[str, float]) -> Dict:
        """
        Main entry point called by the Orchestrator.
        """
        lat, lng = coords.get("lat"), coords.get("lng")
        
        if not lat or not lng:
            encounter_json["location_confidence"] = "low"
            return encounter_json

        # 1. Get Administrative Hierarchy (Reverse Geocode)
        admin_data = self._get_admin_hierarchy(lat, lng)
        
        # 2. Find Nearest Health Facilities
        facilities = self._find_nearby_facilities(lat, lng)
        
        # 3. Calculate ETAs for the top 3 facilities
        if facilities:
            facilities = self._add_etas(lat, lng, facilities[:3])

        # Merge into encounter JSON
        encounter_json["location"] = {"type": "Point", "coordinates": [lng, lat]}
        encounter_json["admin_hierarchy"] = admin_data
        encounter_json["nearest_facilities"] = facilities
        encounter_json["location_confidence"] = "high"
        
        return encounter_json

    def _get_admin_hierarchy(self, lat, lng) -> Dict:
        """Maps Google Address Components to Kenya's Hierarchy"""
        res = self.gmaps.reverse_geocode((lat, lng))
        hierarchy = {
            "village": "Unknown",
            "ward": "Unknown",
            "sub_county": "Unknown",
            "county": "Unknown"
        }

        if not res:
            return hierarchy

        # Standard mapping for Kenya Administrative structure in Google Maps
        for component in res[0]['address_components']:
            types = component['types']
            if 'neighborhood' in types:
                hierarchy['village'] = component['long_name']
            elif 'administrative_area_level_3' in types:
                hierarchy['ward'] = component['long_name']
            elif 'administrative_area_level_2' in types:
                hierarchy['sub_county'] = component['long_name']
            elif 'administrative_area_level_1' in types:
                hierarchy['county'] = component['long_name']

        return hierarchy

    def _find_nearby_facilities(self, lat, lng) -> List[Dict]:
        """Finds open hospitals or health clinics within 50km"""
        places_result = self.gmaps.places_nearby(
            location=(lat, lng),
            radius=50000,
            type='hospital',
            rank_by='prominence'
        )

        facilities = []
        for place in places_result.get('results', []):
            facilities.append({
                "place_id": place['place_id'],
                "name": place['name'],
                "address": place.get('vicinity', ''),
                "distance_km": 0, # Placeholder
                "open_now": place.get('opening_hours', {}).get('open_now', False),
                "has_emergency": 'emergency' in place.get('types', [])
            })
        return facilities

    def _add_etas(self, lat, lng, facilities: List[Dict]) -> List[Dict]:
        """Calculates real-time driving ETA using Directions API"""
        destinations = [f"place_id:{f['place_id']}" for f in facilities]
        
        matrix = self.gmaps.distance_matrix(
            origins=[(lat, lng)],
            destinations=destinations,
            mode="driving",
            departure_time=datetime.now()
        )

        for i, element in enumerate(matrix['rows'][0]['elements']):
            if element['status'] == 'OK':
                facilities[i]["distance_km"] = round(element['distance']['value'] / 1000, 1)
                facilities[i]["eta_minutes"] = int(element['duration_in_traffic']['value'] / 60)
        
        return facilities