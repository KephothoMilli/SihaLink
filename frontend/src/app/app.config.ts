import { ApplicationConfig, ErrorHandler, Injectable } from '@angular/core';
import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { routes } from './app.routes';

// ── Dynatrace RUM Error Handler ───────────────────────────────────────────────
// Forwards every uncaught Angular exception to window.dtrum.reportError() so
// it appears in the Dynatrace RUM session timeline alongside network errors and
// Core Web Vital regressions.
//
// The dtrum stub in index.html ensures this never throws even when the RUM
// script is not loaded (local dev, wrong URL, network offline).
//
// Reference:
//   https://www.dynatrace.com/support/help/how-to-use-dynatrace/
//   real-user-monitoring/setup-and-configuration/web-applications/
//   additional-configuration/customize-rum
@Injectable()
export class DynatraceErrorHandler implements ErrorHandler {
  handleError(error: unknown): void {
    // Report to Dynatrace RUM (no-op when dtrum stub is active)
    try {
      const dtrum = (window as any).dtrum;
      if (typeof dtrum?.reportError === 'function') {
        dtrum.reportError(error);
      }
    } catch {
      // Never let the error handler itself crash the app
    }

    // Always re-log to console so developers still see errors locally
    console.error('[SihaLink]', error);
  }
}

export const appConfig: ApplicationConfig = {
  providers: [
    provideRouter(routes),
    provideHttpClient(),
    provideAnimationsAsync(),

    // Replace the default Angular ErrorHandler with the Dynatrace-aware one
    { provide: ErrorHandler, useClass: DynatraceErrorHandler },
  ],
};
