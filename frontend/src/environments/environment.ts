/**
 * SihaLink — Development environment configuration.
 * Vite dev server proxies /tool, /encounter, /health to localhost:8000.
 */
export const environment = {
  production: false,
  apiUrl: 'http://localhost:8000',
  apiTimeout: 30_000,
  enableLogging: true,

  // Feature flags — all on in dev
  features: {
    silentPandemicScan: true,
    followUpTracking: true,
    protocolSearch: true,
    chwRegistry: true,
    referralTracking: true,
    crossCountySpread: true,
    offlineSync: true,
    liveAudio: true, // Gemini Live API bidirectional audio
    tts: true, // Text-to-Speech responses
  },

  // Surveillance schedule (ms)
  surveillanceIntervalMs: 6 * 60 * 60 * 1000, // 6 hours
  silentPandemicWeeks: 4,

  // Follow-up polling interval (ms)
  followUpPollIntervalMs: 5 * 60 * 1000, // 5 minutes

  // Human-in-the-loop gate timeout (ms) — must match backend
  gateTimeoutMs: 60_000,
};
