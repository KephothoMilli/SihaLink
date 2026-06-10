# Quick Start Guide - SihaLink Frontend (Angular 23)

## Prerequisites

- Node.js 18+ and npm 9+
- Backend orchestrator running (<http://localhost:8000>)

## Installation

```bash
cd frontend
npm install
```

## Development Server

```bash
npm run dev
```

Open <http://localhost:5173> in your browser.

The app will:

- Hot-reload on file changes
- Proxy API calls to <http://localhost:8000>
- Display agent status dashboard

## Project Structure

```
src/
├── app/                    # Components and routing
│   ├── app.component.*    # Root component
│   ├── app.routes.ts      # Route definitions
│   ├── dashboard/         # Dashboard page
│   ├── encounters/        # Encounter management
│   └── agents-ui/         # Agent UI components
├── services/              # Business logic
│   ├── root-agent.service.ts    # Main orchestrator
│   ├── api.service.ts           # HTTP layer
│   └── agents/                  # Individual agent services
└── styles/                # Global styles
```

## Available Pages

| Page         | Route                  | Purpose                     |
| ------------ | ---------------------- | --------------------------- |
| Dashboard    | `/dashboard`           | Overview & agent status     |
| Intake Agent | `/agents/intake`       | Record audio & extract data |
| Geo Agent    | `/agents/geo`          | Location enrichment         |
| Data Agent   | `/agents/data`         | Search & manage encounters  |
| Notify Agent | `/agents/notify`       | Send alerts                 |
| Surveillance | `/agents/surveillance` | Monitor trends              |
| Encounters   | `/encounters`          | View all sessions           |

## Key Features

### 1. **Intake Agent** (`/agents/intake`)

- ✓ Record audio from microphone
- ✓ Extract clinical data using AI
- ✓ Display symptoms, vitals, assessment
- ✓ Request clarifications

### 2. **Geo Agent** (`/agents/geo`)

- ✓ Get current location (GPS)
- ✓ Find nearest health facilities
- ✓ Display administrative hierarchy
- ✓ Calculate ETAs

### 3. **Data Agent** (`/agents/data`)

- ✓ Search encounters by symptoms
- ✓ View encounter details
- ✓ Analyze trends over time
- ✓ Vector semantic search

### 4. **Notify Agent** (`/agents/notify`)

- ✓ Send notifications to Telegram/SMS
- ✓ Register health workers
- ✓ Track delivery status
- ✓ Set alert priority levels

### 5. **Surveillance Agent** (`/agents/surveillance`)

- ✓ Monitor disease trends
- ✓ Detect outbreak alerts
- ✓ Identify disease clusters
- ✓ Generate reports

## How to Use

### Recording a Clinical Encounter

1. Click **Intake Agent** from dashboard
2. Click **🎤 Start Recording**
3. Speak the patient's symptoms into the microphone
4. Click **⏹ Stop Recording**
5. Click **✓ Process Audio**
6. View extracted clinical information
7. System will automatically:
   - Get location (Geo Agent)
   - Find nearby facilities
   - Store in MongoDB (Data Agent)
   - Send alerts if needed (Notify Agent)
   - Trigger surveillance (Surveillance Agent)

### Searching Encounters

1. Click **Data Agent** from dashboard
2. Enter search query (e.g., "malaria fever")
3. Click **🔍 Search**
4. View results with relevance scores
5. Click encounter to see full details

### Checking Health Alerts

1. Click **Surveillance Agent** from dashboard
2. Enter region name
3. Click **🚨 Get Alerts**
4. View active outbreaks and anomalies
5. Check disease clusters
6. Review trends

### Managing Recipients

1. Click **Notify Agent** from dashboard
2. Scroll to "Registered Recipients"
3. Click **➕ Register New**
4. Enter health worker details
5. Click **✓ Register**
6. Now can send them alerts

## Development Tasks

### Add a New Component

```typescript
// Create: src/app/my-feature/my-feature.component.ts
import { Component } from "@angular/core";
import { CommonModule } from "@angular/common";

@Component({
  selector: "app-my-feature",
  templateUrl: "./my-feature.component.html",
  styleUrls: ["./my-feature.component.css"],
  standalone: true,
  imports: [CommonModule],
})
export class MyFeatureComponent {}
```

### Add a New Route

Edit `src/app/app.routes.ts`:

```typescript
{
  path: 'my-feature',
  loadComponent: () => import('./my-feature/my-feature.component')
    .then(m => m.MyFeatureComponent)
}
```

### Use a Service

```typescript
constructor(private myService: MyService) {}

ngOnInit() {
  this.myService.getData().then(data => {
    this.data = data;
  });
}
```

## Common Issues

### 1. **API Not Connecting**

```bash
# Check backend is running
curl http://localhost:8000/health/intake
# Should return { "status": "ok" }
```

### 2. **Microphone Not Working**

- Check browser permissions
- HTTPS required in production (for getUserMedia)

### 3. **Components Not Appearing**

```bash
# Clear node_modules and reinstall
rm -rf node_modules package-lock.json
npm install
npm run dev
```

### 4. **TypeScript Errors**

```bash
# Rebuild
npm run build
# Check errors in console
```

## Environment Variables

Create `.env.local` in frontend directory:

```
VITE_API_URL=http://localhost:8000
VITE_ENABLE_MOCK_DATA=false
VITE_DEBUG=true
```

## Build for Production

```bash
npm run build
# Outputs: dist/

# Deploy to Firebase
firebase deploy --only hosting
```

## Testing

Currently no automated tests. To add:

```bash
npm install --save-dev vitest @vitest/ui
```

Then create `src/app/my.component.spec.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { MyComponent } from "./my.component";

describe("MyComponent", () => {
  it("should create", () => {
    expect(true).toBe(true);
  });
});
```

Run tests:

```bash
npm run test
```

## Useful Commands

```bash
# Development
npm run dev              # Start dev server
npm run build           # Build for production
npm run preview         # Preview production build

# Firebase
firebase login          # Authenticate
firebase init           # Initialize Firebase
firebase deploy         # Deploy to Firebase

# Utilities
npm list                # List dependencies
npm outdated            # Check for updates
npm audit              # Security audit
```

## Performance Tips

1. **Use OnPush detection**: `changeDetection: ChangeDetectionStrategy.OnPush`
2. **Unsubscribe from observables**: Use `takeUntilDestroyed()` or ngOnDestroy
3. **Lazy load routes**: ✓ Already configured
4. **Use trackBy in \*ngFor**: `trackBy: trackByFn`

## Debugging

### Chrome DevTools

1. F12 → Sources
2. Set breakpoints
3. Step through code

### Network Tab

1. F12 → Network
2. Monitor API calls
3. Check response times

### Console

```typescript
// In app component
console.log("Session:", this.rootAgent.getActiveSessions());
```

## Next Steps

1. ✓ Frontend fully integrated with all agents
2. ✓ Dashboard shows agent health
3. ✓ All agent UIs implemented
4. Ready for: Testing, UI/UX improvements, deploymentNext:
   - Add charts for visualization
   - Implement form validation
   - Add error handling
   - Write tests
   - Deploy to production

## Support

For issues or questions:

1. Check [ARCHITECTURE.md](./ARCHITECTURE.md) for detailed docs
2. Review code comments in services
3. Check backend logs
4. Open a GitHub issue

Happy coding! 🏥
