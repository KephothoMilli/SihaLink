# SihaLink Frontend - Angular 23 Multi-Agent System

> Modern Angular 23 frontend for the multi-agent healthcare system. Unified interface to access all specialized agents through a single Root Agent Orchestrator.

## 🎯 Overview

**SihaLink** connects community health workers with a network of specialized AI agents for clinical decision support:

- **Intake Agent** 🎤: Extract clinical data from audio recordings
- **Geo Agent** 📍: Enrich encounters with location and facility data
- **Data Agent** 💾: Store and search encounters with semantic search
- **Notify Agent** 📨: Send alerts to health workers and supervisors
- **Surveillance Agent** 📊: Monitor disease trends and outbreak detection

All agents are coordinated through a **Root Agent Orchestrator** for seamless workflow automation.

## ⚡ Quick Start

### Prerequisites

- Node.js 18+
- npm 9+
- Backend running on <http://localhost:8000>

### Installation & Development

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173> in your browser.

## 📋 Architecture

### **Standalone Angular 23 Components**

- No NgModule required
- Lazy-loaded routes with `loadComponent()`
- Functional bootstrap with `bootstrapApplication()`
- Tree-shakeable and optimized

### **Service-Based Architecture**

```
Root Agent Service (Orchestrator)
├── Intake Agent Service
├── Geo Agent Service
├── Data Agent Service
├── Notify Agent Service
└── Surveillance Agent Service
    └── API Service (HTTP Layer)
```

Each service maps to a backend agent endpoint.

### **Routing Structure**

```
/dashboard                 - Main overview
/agents/intake            - Clinical data extraction
/agents/geo               - Location enrichment
/agents/data              - Encounter search & management
/agents/notify            - Alert delivery
/agents/surveillance      - Epidemic tracking
/encounters               - Session management
```

## 🚀 Usage

### 1. Dashboard (`/dashboard`)

Central hub showing:

- Agent health status
- Quick links to all agents
- Active encounter sessions
- System overview

### 2. Record Encounter (`/agents/intake`)

```
1. Click "Start Recording" 🎤
2. Describe patient symptoms
3. Click "Stop Recording" ⏹
4. System extracts: symptoms, vitals, assessment
5. Automatic referral workflow triggers
```

### 3. Search Encounters (`/agents/data`)

```
1. Enter symptom/condition query
2. System performs semantic search
3. View matching encounters with scores
4. Click to see full details
5. Analyze trends over time
```

### 4. Send Alerts (`/agents/notify`)

```
1. Enter alert title and message
2. Select recipients
3. Set priority level
4. Send via Telegram/SMS
5. Track delivery status
```

### 5. Monitor Trends (`/agents/surveillance`)

```
1. Select region and date range
2. View active disease alerts
3. Check for disease clusters
4. Analyze symptom trends
5. Get public health recommendations
```

## 🏗️ Project Structure

```
frontend/
├── src/
│   ├── main.ts                           # Bootstrap entry
│   ├── styles/
│   │   └── shared.css                   # Global styles
│   ├── app/
│   │   ├── app.component.ts             # Root component (standalone)
│   │   ├── app.component.html           # Root template
│   │   ├── app.config.ts                # Angular config
│   │   ├── app.routes.ts                # Route definitions
│   │   ├── dashboard/                   # Dashboard page
│   │   ├── encounters/                  # Encounter management
│   │   └── agents-ui/                   # Agent components
│   │       ├── intake-agent/
│   │       ├── geo-agent/
│   │       ├── data-agent/
│   │       ├── notify-agent/
│   │       └── surveillance-agent/
│   └── services/
│       ├── root-agent.service.ts        # Orchestrator
│       ├── api.service.ts               # HTTP layer
│       ├── offline-sync.service.ts      # Offline support
│       └── agents/                      # Individual agent services
│           ├── intake-agent.service.ts
│           ├── geo-agent.service.ts
│           ├── data-agent.service.ts
│           ├── notify-agent.service.ts
│           └── surveillance-agent.service.ts
├── ARCHITECTURE.md                      # Detailed architecture docs
├── QUICKSTART.md                        # Developer quick start
├── package.json                         # Angular 23 + Vite
├── vite.config.ts                       # Vite configuration
└── firebase.json                        # Firebase config
```

## 🔧 Configuration

### Environment Variables

Create `.env.local`:

```
VITE_API_URL=http://localhost:8000
VITE_ENABLE_DEBUG=false
```

### Vite Proxy (Development)

```typescript
// vite.config.ts
proxy: {
  '/api': {
    target: 'http://localhost:8000',
    changeOrigin: true
  }
}
```

## 📦 Building & Deployment

### Development

```bash
npm run dev      # Vite dev server with HMR
```

### Production Build

```bash
npm run build    # Outputs to dist/
npm run preview  # Preview production build locally
```

### Deploy to Firebase Hosting

```bash
firebase login
firebase deploy --only hosting
```

## 🎓 Key Concepts

### **Root Agent Service**

Central coordinator that orchestrates all sub-agents:

```typescript
// Start encounter workflow
const session = await rootAgent.startEncounter({
  audio_base64: audioData,
  latitude: -1.3521,
  longitude: 36.8155,
  chw_id: "CHW-001",
});

// Monitor status
rootAgent.sessionUpdates$.subscribe((session) => {
  console.log("State:", session.state); // IDLE → COMPLETE
});

// Access individual agents
const geoAgent = rootAgent.getGeoAgent();
```

### **Individual Agent Services**

Each agent has specific methods:

```typescript
// Intake: Extract clinical data
const extraction = await intakeAgent.extractClinicalData({
  audio_base64: audioData,
});

// Geo: Enrich with location
const enriched = await geoAgent.enrichEncounter({
  encounter_json: data,
  latitude,
  longitude,
});

// Data: Search encounters
const results = await dataAgent.searchEncounters({
  query: "malaria fever",
  limit: 20,
});

// Notify: Send alerts
const sent = await notifyAgent.sendNotification({
  title: "Urgent",
  message: "Patient needs referral",
  recipients: ["health_worker_id"],
  priority: "critical",
});

// Surveillance: Monitor trends
const alerts = await surveillanceAgent.triggerSurveillance({
  encounter_data: enrichedData,
});
```

### **Standalone Components**

All components are standalone (no NgModule):

```typescript
@Component({
  selector: "app-intake-agent",
  templateUrl: "./intake-agent.component.html",
  styleUrls: ["./intake-agent.component.css"],
  standalone: true,
  imports: [CommonModule, FormsModule],
})
export class IntakeAgentComponent {}
```

### **Lazy Loading Routes**

Routes load components only when needed:

```typescript
{
  path: 'agents/intake',
  loadComponent: () => import('./agents-ui/intake-agent/intake-agent.component')
    .then(m => m.IntakeAgentComponent)
}
```

## 🧪 Testing

Add tests with Vitest:

```bash
npm install --save-dev vitest @vitest/ui
```

Create test file:

```typescript
// src/app/my.component.spec.ts
import { describe, it, expect } from "vitest";
import { MyComponent } from "./my.component";

describe("MyComponent", () => {
  it("should work", () => {
    expect(true).toBe(true);
  });
});
```

Run tests:

```bash
npm run test
```

## 🔄 Offline Support

Features:

- ✓ Detect online/offline status
- ✓ Queue encounters when offline
- ✓ Auto-sync when connection restored
- ✓ Handles network flakiness

## 📊 Performance

- **Tree-shaking**: Unused code eliminated
- **Lazy loading**: Components loaded on demand
- **OnPush detection**: Optimized change detection
- **Vite HMR**: Instant hot reload
- **Small bundle**: ~150KB gzipped (with dependencies)

## 🐛 Troubleshooting

### API Not Connecting

```bash
# Check backend health
curl http://localhost:8000/health/intake

# Check logs
tail -f backend.log
```

### Microphone Permission Denied

- Check browser permissions
- HTTPS required in production
- Allow microphone access in browser settings

### Components Not Loading

```bash
# Clean install
rm -rf node_modules package-lock.json
npm install
npm run dev
```

### TypeScript Errors

```bash
# Rebuild
npm run build

# Check diagnostics
npx tsc --noEmit
```

## 📚 Documentation

- **[ARCHITECTURE.md](./ARCHITECTURE.md)** - Detailed system design
- **[QUICKSTART.md](./QUICKSTART.md)** - Developer quick reference
- **[Angular 23 Docs](https://angular.io)**
- **[Vite Docs](https://vitejs.dev)**

## 🚦 Status

| Feature                | Status      |
| ---------------------- | ----------- |
| Angular 23 Upgrade     | ✅ Complete |
| Standalone Components  | ✅ Complete |
| Routing & Lazy Loading | ✅ Complete |
| Root Agent Service     | ✅ Complete |
| All Agent Services     | ✅ Complete |
| UI Components          | ✅ Complete |
| Offline Support        | ✅ Complete |
| Health Checks          | ✅ Complete |
| Production Build       | ✅ Ready    |
| Unit Tests             | ⏳ Pending  |
| E2E Tests              | ⏳ Pending  |

## 🎯 Next Steps

### Immediate (Ready Now)

- [ ] Deploy to Firebase Hosting
- [ ] Configure backend URL for production
- [ ] Add form validation
- [ ] Implement error boundaries

### Short Term

- [ ] Add Chart.js for visualizations
- [ ] Implement data export (PDF, CSV)
- [ ] Add unit tests
- [ ] Add E2E tests (Cypress)

### Medium Term

- [ ] PWA support for offline-first
- [ ] Real-time updates (WebSockets)
- [ ] Role-based access control (RBAC)
- [ ] Audit logging

### Long Term

- [ ] Multi-language support (i18n)
- [ ] Accessibility audit (WCAG)
- [ ] Performance monitoring
- [ ] Analytics integration

## 📄 License

Part of SihaLink project for Google Cloud Rapid Agent Hackathon (MongoDB track).

## 👥 Contributors

Built by the SihaLink team.

---

**For issues, questions, or feature requests**, please open a GitHub issue or contact the team.

🏥 **SihaLink** - Sauti ya Afya (Voice of Health)
