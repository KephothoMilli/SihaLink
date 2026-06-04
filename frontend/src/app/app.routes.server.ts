import { RenderMode, ServerRoute } from '@angular/ssr';

export const serverRoutes: ServerRoute[] = [
  {
    // All routes are dynamic — rendered on the server at request time,
    // not prerendered at build time (avoids NG0401 bootstrapApplication context error).
    path: '**',
    renderMode: RenderMode.Server,
  },
];
