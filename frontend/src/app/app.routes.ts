/**
 * SihaLink Application Routes
 *
 * Routes for accessing all agents and their functionality through the UI
 */

import { Routes } from '@angular/router';

export const routes: Routes = [
  {
    path: 'agents',
    children: [
      {
        path: 'intake',
        loadComponent: () =>
          import('../app/agents-ui/intake-agent/intake-agent.component').then(
            (m) => m.IntakeAgentComponent,
          ),
      },
      {
        path: 'geo',
        loadComponent: () =>
          import('../app/agents-ui/geo-agent/geo-agent.component').then(
            (m) => m.GeoAgentComponent,
          ),
      },
      {
        path: 'data',
        loadComponent: () =>
          import('../app/agents-ui/data-agent/data-agent.component').then(
            (m) => m.DataAgentComponent,
          ),
      },
      {
        path: 'notify',
        loadComponent: () =>
          import('../app/agents-ui/notify-agent/notify-agent.component').then(
            (m) => m.NotifyAgentComponent,
          ),
      },
      {
        path: 'surveillance',
        loadComponent: () =>
          import('../app/agents-ui/surveillance-agent/surveillance-agent.component').then(
            (m) => m.SurveillanceAgentComponent,
          ),
      },
      {
        path: '',
        redirectTo: 'intake',
        pathMatch: 'full',
      },
    ],
  },
  {
    path: 'encounters',
    loadComponent: () =>
      import('../app/encounters/encounters.component').then(
        (m) => m.EncountersComponent,
      ),
  },
  {
    path: 'dashboard',
    loadComponent: () =>
      import('../app/dashboard/dashboard.component').then(
        (m) => m.DashboardComponent,
      ),
  },
  {
    path: '',
    redirectTo: '/dashboard',
    pathMatch: 'full',
  },
  {
    path: '**',
    redirectTo: '/dashboard',
  },
];
