# Frontend-Backend Integration Guide

## 📡 How All Agents Are Connected Through the Root Agent

The SihaLink frontend uses a **Root Agent Service** that coordinates all sub-agents through the backend Orchestrator. Here's how it all works:

## 🔗 Connection Flow

```
┌──────────────────────────────────────────────────────────────┐
│                   FRONTEND (Angular 23)                      │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │          Root Agent Service                            │  │
│  │  - Orchestrates agent workflow                        │  │
│  │  - Manages encounter sessions                         │  │
│  │  - Broadcasts status updates                          │  │
│  └────────────────────────────────────────────────────────┘  │
│         │         │          │         │         │           │
│         ↓         ↓          ↓         ↓         ↓           │
│  ┌─────────┐ ┌──────┐ ┌─────────┐ ┌─────────┐ ┌──────┐    │
│  │ Intake  │ │ Geo  │ │  Data   │ │ Notify  │ │Surv. │    │
│  │ Service │ │Serv. │ │ Service │ │ Service │ │Serv. │    │
│  └─────────┘ └──────┘ └─────────┘ └─────────┘ └──────┘    │
│         │         │          │         │         │           │
│         └─────────┴──────────┴─────────┴─────────┘           │
│                         │                                    │
│  ┌────────────────────────────────────────────────────────┐  │
│  │        API Service (HTTP Layer)                        │  │
│  │  - Wraps all HTTP calls                               │  │
│  │  - Handles errors and retries                         │  │
│  │  - Base URL: http://localhost:8000                    │  │
│  └────────────────────────────────────────────────────────┘  │
│                         │                                    │
└─────────────────────────┼────────────────────────────────────┘
                          │ HTTP
                          ↓
┌──────────────────────────────────────────────────────────────┐
│              BACKEND (Google Agent Runtime)                  │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │    Orchestrator Agent (FastAPI)                       │  │
│  │  - Coordinates all sub-agents                        │  │
│  │  - Manages state machine                             │  │
│  │  - Exposes tool endpoints                            │  │
│  └────────────────────────────────────────────────────────┘  │
│         │         │          │         │         │           │
│         ↓         ↓          ↓         ↓         ↓           │
│  ┌─────────┐ ┌──────┐ ┌─────────┐ ┌─────────┐ ┌──────┐    │
│  │ Intake  │ │ Geo  │ │  Data   │ │ Notify  │ │Surv. │    │
│  │ Agent   │ │Agent │ │ Agent   │ │ Agent   │ │Agent │    │
│  └─────────┘ └──────┘ └─────────┘ └─────────┘ └──────┘    │
│                                                               │
│  External Services:                                          │
│  ├─ Gemini AI (Speech → Clinical data)                     │
│  ├─ Google Maps API (Location → Facilities)                │
│  ├─ MongoDB Atlas (Store embeddings)                       │
│  ├─ Telegram Bot (Send notifications)                      │
│  └─ Spanner DB (Surveillance data)                         │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

## 📱 Usage from Angular Components

### **Example 1: Starting an Encounter**

```typescript
// File: src/app/agents-ui/intake-agent/intake-agent.component.ts
import { Component } from "@angular/core";
import { RootAgentService } from "../../services/root-agent.service";

@Component({
  selector: "app-intake",
  standalone: true,
})
export class IntakeAgentComponent {
  constructor(private rootAgent: RootAgentService) {}

  async startEncounter() {
    try {
      // This triggers the ENTIRE workflow:
      // 1. Audio → Intake Agent
      // 2. Extraction → Geo Agent
      // 3. Enriched data → Data Agent
      // 4. Notifications → Notify Agent
      // 5. Surveillance → Surveillance Agent

      const session = await this.rootAgent.startEncounter({
        audio_base64: this.audioBase64,
        latitude: -1.3521,
        longitude: 36.8155,
        chw_id: "CHW-001",
      });

      console.log("Encounter session:", session);
      // Output: { sessionId, state: 'COMPLETE', data: {...} }
    } catch (error) {
      console.error("Failed to start encounter:", error);
    }
  }

  // Monitor real-time updates
  ngOnInit() {
    this.rootAgent.sessionUpdates$.subscribe((session) => {
      console.log("Session state:", session.state);
      // IDLE → LISTENING → EXTRACTING → GEOCODING
      // → STORING → DECISION_GATE → NOTIFYING → COMPLETE
    });
  }
}
```

### **Example 2: Accessing Individual Agents**

```typescript
// Direct access to Intake Agent
const intakeAgent = this.rootAgent.getIntakeAgent();
const result = await intakeAgent.extractClinicalData({
  audio_base64: audioData,
});
// Returns: { symptoms, vitals, assessment, confidence_score }

// Direct access to Geo Agent
const geoAgent = this.rootAgent.getGeoAgent();
const enriched = await geoAgent.enrichEncounter({
  encounter_json: clinicalData,
  latitude: -1.3521,
  longitude: 36.8155,
});
// Returns: { admin_hierarchy, nearest_facilities, recommended_facility }

// Direct access to Data Agent
const dataAgent = this.rootAgent.getDataAgent();
const stored = await dataAgent.insertEncounter({
  enriched_encounter: enrichedData,
});
// Returns: { id, encounter_json, vector_embedding, timestamp }

// Direct access to Notify Agent
const notifyAgent = this.rootAgent.getNotifyAgent();
const notification = await notifyAgent.sendNotification({
  title: "Urgent Alert",
  message: "Patient needs referral",
  recipients: ["recipient_1", "+254712345678"],
  priority: "critical",
});
// Returns: { notification_id, sent_at, recipients_reached, status }

// Direct access to Surveillance Agent
const surveillanceAgent = this.rootAgent.getSurveillanceAgent();
const alerts = await surveillanceAgent.triggerSurveillance({
  encounter_id: "encounter-123",
  encounter_data: enrichedData,
});
// Returns: [ { alert_type, severity, recommendations } ]
```

## 🔄 Encounter Workflow State Machine

The Root Agent manages this state machine:

```typescript
type EncounterState =
  | "IDLE" // Initial state
  | "LISTENING" // Waiting for user input
  | "EXTRACTING" // Intake Agent processing audio
  | "GEOCODING" // Geo Agent enriching location
  | "STORING" // Data Agent inserting to MongoDB
  | "DECISION_GATE" // Waiting for human-in-the-loop confirmation
  | "NOTIFYING" // Notify Agent sending alerts
  | "COMPLETE"; // Workflow finished

// Each state change broadcasts via sessionUpdates$
rootAgent.sessionUpdates$.subscribe((session) => {
  console.log("State:", session.state);
  console.log("Data:", session.data); // Contains extraction, location, etc.
  console.log("Error:", session.error); // If any error occurred
});
```

## 🌐 Backend Endpoints (Called via Root Agent)

All HTTP calls go through `ApiService` which calls these backend endpoints:

| Endpoint                        | Method | Purpose                  | Service      |
| ------------------------------- | ------ | ------------------------ | ------------ |
| `/tool/start_encounter`         | POST   | Begin encounter workflow | Orchestrator |
| `/tool/route_to_intake`         | POST   | Extract from audio       | Intake       |
| `/tool/route_to_geo`            | POST   | Enrich with location     | Geo          |
| `/tool/route_to_data`           | POST   | Store in MongoDB         | Data         |
| `/tool/route_to_notify`         | POST   | Send notification        | Notify       |
| `/tool/trigger_surveillance`    | POST   | Analyze for surveillance | Surveillance |
| `/encounter/:sessionId/status`  | GET    | Get session state        | Orchestrator |
| `/encounter/:sessionId/confirm` | POST   | Confirm gate decision    | Orchestrator |
| `/health/:agent`                | GET    | Check agent health       | Any          |

## 🛠️ Service Integration Points

### **API Service** (Low-level HTTP)

```typescript
// File: src/services/api.service.ts
private async post<T = any>(path: string, body: any = {}): Promise<T>
private async get<T = any>(path: string): Promise<T>
```

### **Root Agent Service** (Orchestrator)

```typescript
// File: src/services/root-agent.service.ts
async startEncounter(params): Promise<EncounterSession>
async getEncounterStatus(sessionId): Promise<EncounterSession>
async confirmEncounterDecision(sessionId, confirmed): Promise<void>
async checkAgentHealth(): Promise<void>
```

### **Individual Agent Services**

```typescript
// Intake
async extractClinicalData(request): Promise<ExtractionResult>

// Geo
async enrichEncounter(request): Promise<GeoEnrichment>

// Data
async insertEncounter(request): Promise<StoredEncounter>

// Notify
async sendNotification(request): Promise<NotificationResult>

// Surveillance
async triggerSurveillance(request): Promise<SurveillanceAlert[]>
```

## 🔌 Dependency Injection Chain

```typescript
// 1. Services are provided at root level
@Injectable({ providedIn: 'root' })
export class RootAgentService { }

// 2. Components inject services
constructor(private rootAgent: RootAgentService) { }

// 3. Services inject API layer
constructor(private api: ApiService) { }

// 4. API Service makes HTTP calls
fetch(`${this.base}${path}`, { method: 'POST', body: JSON.stringify(data) })
```

## 📊 Session Data Structure

Each encounter session maintains:

```typescript
interface EncounterSession {
  sessionId: string; // Unique ID
  state: EncounterState; // Current state
  data: {
    audio?: string; // Base64 audio
    extraction?: ExtractionResult; // Intake output
    location?: { latitude; longitude }; // GPS coords
    geoEnriched?: GeoEnrichment; // Geo output
    mongoStored?: StoredEncounter; // Data Agent output
    notifications?: NotificationResult[]; // Notify output
    surveillanceData?: SurveillanceAlert[]; // Surveillance output
  };
  timestamp: number; // Creation time
  error?: string; // Error if any
}
```

## 🚀 Real-World Scenario

**Scenario**: CHW records patient with fever symptoms

```
Step 1: User clicks "Start Recording" in Intake Agent UI
        ↓
Step 2: Audio captured and converted to base64
        ↓
Step 3: rootAgent.startEncounter({audio_base64, location})
        ↓
Step 4: Intake Agent (backend) processes audio
        ├─ Uses Gemini AI to extract symptoms, vitals
        ├─ Returns: { symptoms: ['fever', 'cough'], vitals: {...} }
        └─ Frontend updates: sessionUpdates$.next({state: 'EXTRACTING'})
        ↓
Step 5: Geo Agent (backend) enriches data
        ├─ Gets location from coordinates
        ├─ Finds nearest health facilities
        ├─ Returns: { facilities: [...], admin_hierarchy: {...} }
        └─ Frontend updates: sessionUpdates$.next({state: 'GEOCODING'})
        ↓
Step 6: Data Agent (backend) stores in MongoDB
        ├─ Creates vector embedding
        ├─ Stores encounter with metadata
        ├─ Returns: { id: 'enc-123', stored_at: '2024-05-31' }
        └─ Frontend updates: sessionUpdates$.next({state: 'STORING'})
        ↓
Step 7: Check if urgent referral needed
        ├─ If yes: sessionUpdates$.next({state: 'DECISION_GATE'})
        ├─ UI shows confirmation dialog
        └─ Wait for CHW confirmation
        ↓
Step 8: Send notifications (if confirmed)
        ├─ Notify Agent sends to Telegram
        ├─ Returns: { notification_id, status: 'sent' }
        └─ Frontend updates: sessionUpdates$.next({state: 'NOTIFYING'})
        ↓
Step 9: Surveillance Agent analyzes for trends
        ├─ Checks for disease clusters
        ├─ Triggers alerts if anomalies detected
        ├─ Returns: [ { alert_type: 'outbreak', severity: 'high' } ]
        └─ Frontend updates: sessionUpdates$.next({state: 'COMPLETE'})
        ↓
Step 10: Session complete, data available for review
        └─ User can view full encounter in /encounters
```

## 🔐 Authentication Flow

Currently uses environment-based API keys (backend):

```typescript
// Backend uses env vars for APIs
GEMINI_API_KEY = xxx;
GOOGLE_MAPS_API_KEY = xxx;
MONGODB_ATLAS_URI = xxx;

// Future: Add OAuth2/JWT for frontend auth
```

## 🧪 Testing Integration

```typescript
// Mock Root Agent Service for testing
@Injectable()
export class MockRootAgentService {
  sessionUpdates$ = of({
    sessionId: 'test-session',
    state: 'COMPLETE',
    data: { extraction: {...} }
  });

  async startEncounter() {
    return { sessionId: 'test', state: 'COMPLETE' };
  }
}

// In test
providers: [
  { provide: RootAgentService, useClass: MockRootAgentService }
]
```

## 📈 Monitoring & Debugging

### **Health Checks**

```typescript
// Automatically called on app startup
rootAgent.checkAgentHealth().then((status) => {
  console.log("Intake:", status.intake ? "✓" : "✕");
  console.log("Geo:", status.geo ? "✓" : "✕");
  // ...
});
```

### **Session Tracking**

```typescript
// View all active sessions
const sessions = rootAgent.getActiveSessions();
console.log(`${sessions.length} active sessions`);

// Monitor specific session
rootAgent.sessionUpdates$.subscribe((session) => {
  if (session?.state === "COMPLETE") {
    console.log("Session complete:", session.sessionId);
  }
});
```

### **Error Handling**

```typescript
try {
  await rootAgent.startEncounter(params);
} catch (error) {
  // Error is caught and session.error is set
  const session = rootAgent.getActiveSessions()[0];
  console.error("Encounter error:", session.error);
}
```

---

## Summary

✅ **All agents are fully integrated via Root Agent Service**
✅ **Frontend components access agents through single orchestrator**  
✅ **Real-time state updates via RxJS observables**
✅ **Type-safe service interfaces**
✅ **Automatic workflow orchestration**
✅ **Health monitoring and error handling**

🎉 **Ready for production deployment!**
