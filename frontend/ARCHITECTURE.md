# SihaLink Frontend Architecture - Angular 23

## Overview

SihaLink Frontend is a modern Angular 23 application that serves as the UI for the multi-agent healthcare system. It provides a unified interface to access all specialized agents (Intake, Geo, Data, Notify, Surveillance) through the Root Agent Orchestrator.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                      App Component                          │
│                   (Standalone, Angular 23)                  │
├─────────────────────────────────────────────────────────────┤
│  Router: /dashboard, /agents/*, /encounters                 │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │            Root Agent Service                        │   │
│  │    Central coordinator for all agents               │   │
│  │  - Orchestrates workflow: Intake → Geo → Data      │   │
│  │  - Manages encounter sessions                       │   │
│  │  - Provides agent health status                     │   │
│  └──────────────────────────────────────────────────────┘   │
│         ↓          ↓           ↓          ↓           ↓     │
│     ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌──────┐
│     │ Intake  │ │   Geo   │ │  Data   │ │ Notify  │ │Surv. │
│     │ Service │ │ Service │ │ Service │ │ Service │ │Serv. │
│     └─────────┘ └─────────┘ └─────────┘ └─────────┘ └──────┘
│         ↓          ↓           ↓          ↓           ↓     │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              API Service                            │   │
│  │  Wraps HTTP calls to Orchestrator Backend           │   │
│  │  Base URL: http://localhost:8000 or env VITE_API   │   │
│  └──────────────────────────────────────────────────────┘   │
│                         ↓                                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │       Backend: Google Agent Runtime                 │   │
│  │  - Orchestrator (FastAPI)                          │   │
│  │  - Intake, Geo, Data, Notify, Surveillance agents │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Project Structure

```
frontend/
├── src/
│   ├── main.ts                                 # Bootstrap entry (Angular 23)
│   ├── styles/
│   │   └── shared.css                         # Global styles
│   │
│   ├── app/
│   │   ├── app.component.ts                  # Root standalone component
│   │   ├── app.component.html                # Root template with router-outlet
│   │   ├── app.component.css                 # Root styles
│   │   ├── app.config.ts                     # Angular config
│   │   ├── app.routes.ts                     # Route definitions
│   │   │
│   │   ├── dashboard/                        # Dashboard page
│   │   │   ├── dashboard.component.ts
│   │   │   └── dashboard.component.html
│   │   │
│   │   ├── encounters/                       # Encounters management
│   │   │   ├── encounters.component.ts
│   │   │   └── encounters.component.html
│   │   │
│   │   └── agents-ui/                        # Agent UI components
│   │       ├── intake-agent/
│   │       │   ├── intake-agent.component.ts
│   │       │   └── intake-agent.component.html
│   │       ├── geo-agent/
│   │       │   ├── geo-agent.component.ts
│   │       │   └── geo-agent.component.html
│   │       ├── data-agent/
│   │       │   ├── data-agent.component.ts
│   │       │   └── data-agent.component.html
│   │       ├── notify-agent/
│   │       │   ├── notify-agent.component.ts
│   │       │   └── notify-agent.component.html
│   │       └── surveillance-agent/
│   │           ├── surveillance-agent.component.ts
│   │           └── surveillance-agent.component.html
│   │
│   └── services/
│       ├── api.service.ts                   # HTTP layer
│       ├── root-agent.service.ts            # Root orchestrator
│       ├── offline-sync.service.ts          # Offline support
│       │
│       └── agents/                          # Individual agent services
│           ├── intake-agent.service.ts
│           ├── geo-agent.service.ts
│           ├── data-agent.service.ts
│           ├── notify-agent.service.ts
│           └── surveillance-agent.service.ts
│
├── package.json                             # Angular 23 deps
├── vite.config.ts                          # Vite config
├── tsconfig.json                           # TypeScript config
└── firebase.json                           # Firebase config
```

## Upgrade to Angular 23 Key Changes

### 1. **Standalone Components (No NgModule required)**

```typescript
// Old way (NgModule)
@NgModule({ ... })
export class AppModule { }

// New way (Standalone)
@Component({
  standalone: true,
  imports: [CommonModule, RouterModule]
})
export class AppComponent { }
```

### 2. **Functional Bootstrap**

```typescript
// Old way
platformBrowserDynamic().bootstrapModule(AppModule);

// New way
bootstrapApplication(AppComponent, appConfig);
```

### 3. **Standalone Routes**

- Routes are now defined in `app.routes.ts`
- Components load lazily using `loadComponent()`
- No lazy-loaded modules needed

### 4. **Dependency Injection (RxJS + Services)**

- Services use `providedIn: 'root'` singleton pattern
- BehaviorSubjects for reactive state management
- No decorator-based DI in bootstrap

## Services Architecture

### **Root Agent Service** (`root-agent.service.ts`)

Central orchestrator that coordinates all agents:

```typescript
// Start a complete encounter workflow
await rootAgent.startEncounter({
  audio_base64: audioData,
  latitude: -1.3521,
  longitude: 36.8155,
  chw_id: "CHW123",
});

// States: IDLE → LISTENING → EXTRACTING → GEOCODING
//        → STORING → DECISION_GATE → NOTIFYING → COMPLETE

// Access individual agents
const geoAgent = rootAgent.getGeoAgent();
const dataAgent = rootAgent.getDataAgent();

// Monitor status
rootAgent.agentStatus$.subscribe((status) => {
  console.log("Intake agent:", status.intake ? "✓" : "✕");
});

// Watch session updates
rootAgent.sessionUpdates$.subscribe((session) => {
  console.log("Session state:", session.state);
});
```

### **Agent Services** (Individual Agents)

Each agent has a dedicated service:

#### **Intake Agent**

```typescript
// Extract clinical data from audio
const result = await intakeAgent.extractClinicalData({
  audio_base64: audioData,
  clarification_answers: ["Yes", "No"],
});
// Returns: ExtractionResult { symptoms, vitals, assessment, ... }

// Clarify extraction
const refined = await intakeAgent.clarifyExtraction({
  original_extraction: result,
  clarification_answer: "Patient has fever",
});
```

#### **Geo Agent**

```typescript
// Enrich with location data
const enriched = await geoAgent.enrichEncounter({
  encounter_json: clinicalData,
  latitude: -1.3521,
  longitude: 36.8155,
});
// Returns: GeoEnrichment { admin_hierarchy, nearest_facilities, ... }

// Find facilities
const facilities = await geoAgent.findNearestFacilities({ latitude, longitude }, radius_km);
```

#### **Data Agent**

```typescript
// Store encounter in MongoDB
const stored = await dataAgent.insertEncounter({
  enriched_encounter: enrichedData,
});
// Returns: StoredEncounter { id, vector_embedding, timestamp, ... }

// Search encounters
const results = await dataAgent.searchEncounters({
  query: "malaria fever",
  limit: 20,
});

// Trend analysis
const trends = await dataAgent.getTrendAnalysis({
  region: "Nairobi County",
  time_range_days: 30,
});
```

#### **Notify Agent**

```typescript
// Send notification
const result = await notifyAgent.sendNotification({
  title: "Urgent Alert",
  message: "Patient needs referral",
  recipients: ["recipient_id_1", "+254712345678"],
  priority: "high",
});

// Register recipient
await notifyAgent.registerRecipient({
  name: "Dr. Jane",
  role: "Supervisor",
  telegram_id: "123456789",
});
```

#### **Surveillance Agent**

```typescript
// Trigger surveillance analysis
const alerts = await surveillanceAgent.triggerSurveillance({
  encounter_id: "enc-123",
  encounter_data: enrichedData,
});
// Returns: SurveillanceAlert[] { alert_type, severity, recommendations }

// Get region alerts
const alerts = await surveillanceAgent.getRegionAlerts({
  region: "Nairobi County",
  start_date: Date.now() - 30 * 24 * 60 * 60 * 1000,
  end_date: Date.now(),
});

// Check disease clusters
const clusters = await surveillanceAgent.checkDiseaseClusters({
  disease: "malaria",
  region: "Nairobi County",
  radius_km: 50,
});
```

### **API Service** (`api.service.ts`)

Low-level HTTP wrapper:

```typescript
// Private methods
post<T>(path: string, body: any): Promise<T>
get<T>(path: string): Promise<T>

// Public methods map to backend endpoints
startEncounter(body): Promise<any>
getEncounterStatus(sessionId): Promise<any>
// ... etc
```

## UI Components

### **Dashboard** (`/dashboard`)

- Agent status indicators
- Quick access to all agents
- Active sessions list

### **Intake Agent** (`/agents/intake`)

- Audio recording interface
- Real-time extraction display
- Vitals, symptoms, assessment
- Clarification workflow

### **Geo Agent** (`/agents/geo`)

- Location input or GPS detection
- Nearest facility search
- Administrative hierarchy display
- ETA calculation

### **Data Agent** (`/agents/data`)

- Semantic search across encounters
- Encounter detail view
- Trend analysis
- Export capabilities

### **Notify Agent** (`/agents/notify`)

- Notification form
- Priority selection
- Recipient management
- Delivery status tracking

### **Surveillance Agent** (`/agents/surveillance`)

- Alerts dashboard
- Symptom trend visualization
- Disease cluster detection
- Public health recommendations

### **Encounters** (`/encounters`)

- List all active/completed encounters
- View full encounter workflow state
- Session cleanup

## Routing Strategy

```typescript
// app.routes.ts
export const routes: Routes = [
  {
    path: "agents",
    children: [
      { path: "intake", loadComponent: () => IntakeAgentComponent },
      { path: "geo", loadComponent: () => GeoAgentComponent },
      { path: "data", loadComponent: () => DataAgentComponent },
      { path: "notify", loadComponent: () => NotifyAgentComponent },
      { path: "surveillance", loadComponent: () => SurveillanceAgentComponent },
    ],
  },
  { path: "encounters", loadComponent: () => EncountersComponent },
  { path: "dashboard", loadComponent: () => DashboardComponent },
  { path: "", redirectTo: "/dashboard", pathMatch: "full" },
];
```

**Key Features:**

- Lazy-loaded components (not modules)
- Standalone components throughout
- Type-safe routing
- Automatic code splitting

## State Management

**RxJS Observables + Services:**

```typescript
// Root Agent manages state via BehaviorSubjects
agentStatus$ = new BehaviorSubject<AgentStatus>({...});
sessionUpdates$ = new BehaviorSubject<EncounterSession>({...});

// Components subscribe
component.ngOnInit() {
  this.rootAgent.agentStatus$.subscribe(status => {
    this.status = status;
  });
}
```

**No Redux/NgRx needed** - simple RxJS is sufficient for this app.

## Offline Support

- **Offline Sync Service**: Queues encounters when offline
- **Auto-sync**: Syncs when connection restored
- **Online status monitoring**: Listens to `online`/`offline` events
- **Queue persistence**: Stored in memory (can be enhanced with IndexedDB)

## Environment Configuration

```typescript
// vite.config.ts - Dev proxy
proxy: {
  '/api': {
    target: 'http://localhost:8000',
    changeOrigin: true,
    rewrite: (path) => path.replace(/^\/api/, '')
  }
}

// Production - use env var
VITE_API_URL=https://your-agent-runtime-url
```

## Building & Deployment

### Development

```bash
npm install
npm run dev  # Vite dev server
```

### Production

```bash
npm run build  # Outputs dist/
firebase deploy --only hosting
```

### Environment Variables

```
VITE_API_URL=your_orchestrator_url
```

## Health Checks

The app performs health checks on startup and periodically:

```typescript
// App component
async checkAgentHealth() {
  const status = {
    intake: await intakeAgent.healthCheck(),
    geo: await geoAgent.healthCheck(),
    data: await dataAgent.healthCheck(),
    notify: await notifyAgent.healthCheck(),
    surveillance: await surveillanceAgent.healthCheck()
  };
  agentStatus.next(status);
}
```

Health check endpoints: `/health/{agent_name}`

## Angular 23 Benefits

1. **No NgModule boilerplate**: Standalone components everywhere
2. **Smaller bundle size**: Better tree-shaking
3. **Simpler DI**: Functional providers instead of decorator chains
4. **Better performance**: New change detection strategies
5. **Cleaner routing**: Routes are just arrays
6. **Type safety**: Strong typing throughout

## Next Steps

### Immediate

- [ ] Add form validation with Reactive Forms
- [ ] Implement error boundaries
- [ ] Add loading skeletons
- [ ] Create reusable form components

### Short Term

- [ ] Add chart library (Chart.js, ECharts) for visualizations
- [ ] Implement data export (PDF, CSV)
- [ ] Add unit tests (Jasmine/Karma)
- [ ] Add E2E tests (Cypress/Playwright)

### Medium Term

- [ ] Add PWA support for offline functionality
- [ ] Implement real-time updates (WebSockets)
- [ ] Add role-based access control (RBAC)
- [ ] Implement audit logging

### Long Term

- [ ] Multi-language support (i18n)
- [ ] Accessibility audit (WCAG 2.1)
- [ ] Performance monitoring
- [ ] Analytics integration

## Troubleshooting

### CORS Issues

Ensure backend allows CORS from frontend origin:

```python
# FastAPI backend
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://localhost:5173', 'https://your-domain.com'],
    allow_methods=['*'],
    allow_headers=['*']
)
```

### API Not Responding

1. Check backend is running
2. Verify VITE_API_URL env var
3. Check network tab in DevTools
4. Ensure API endpoints match backend paths

### Components Not Loading

1. Verify lazy load paths in routes
2. Check component decorator has `standalone: true`
3. Verify imports in component decorator
4. Check browser console for TypeScript errors

## References

- [Angular 23 Docs](https://angular.io)
- [Vite Documentation](https://vitejs.dev)
- [RxJS Documentation](https://rxjs.dev)
- [Firebase Hosting](https://firebase.google.com/docs/hosting)
