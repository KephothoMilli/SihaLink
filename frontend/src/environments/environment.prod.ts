/**
 * AfyaVoice — Production environment configuration.
 * VITE_API_URL is injected at build time by the CI/CD pipeline.
 * The orchestrator runs on Google Agent Runtime (adk.dev / Cloud Run).
 */
export const environment = {
  production: true,
  apiUrl:
    (import.meta as any).env?.VITE_API_URL ||
    "https://afyavoice-orchestrator-HASH-uc.a.run.app",
  apiTimeout: 30_000,
  enableLogging: false,

  // Feature flags — conservative defaults for production
  features: {
    silentPandemicScan: true,
    followUpTracking: true,
    protocolSearch: true,
    chwRegistry: true,
    referralTracking: true,
    crossCountySpread: true,
    offlineSync: true,
    liveAudio: true,
    tts: true,
  },

  surveillanceIntervalMs: 6 * 60 * 60 * 1000,
  silentPandemicWeeks: 4,
  followUpPollIntervalMs: 5 * 60 * 1000,
  gateTimeoutMs: 60_000,
};
