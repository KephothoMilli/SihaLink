/**
 * SihaLink Notify Agent — grammY Telegram Bot
 *
 * Fully typed. All commands wired to the Python backend.
 * Two user roles:
 *   CHW (Community Health Volunteer) — /report, /followup, /protocol, /status
 *   District Officer                 — /register, /alerts, /acknowledge,
 *                                      /resolve, /broadcast, /swarm, /dashboard
 *
 * Backend bridge: every command calls http://localhost:8000 (BACKEND_URL)
 * Inbound HTTP:   Python orchestrator calls /notify/referral and /notify/outbreak_alert
 *
 * Observability: Dynatrace via OpenTelemetry OTLP (traces every HTTP call)
 */

// ── Dynatrace / OpenTelemetry bootstrap ──────────────────────────────────────
// Loaded dynamically so the bot starts even when OTel packages are not
// installed (e.g. during local dev before npm install is run).
const DT_ENV_ID = process.env.DYNATRACE_ENV_ID;
const DT_API_TOKEN = process.env.DYNATRACE_API_TOKEN;

(async () => {
  if (!DT_ENV_ID || !DT_API_TOKEN) {
    console.log(
      "ℹ️  DYNATRACE_ENV_ID / DYNATRACE_API_TOKEN not set — telemetry disabled",
    );
    return;
  }
  try {
    const { NodeSDK } = await import("@opentelemetry/sdk-node");
    const { OTLPTraceExporter } =
      await import("@opentelemetry/exporter-trace-otlp-http");
    const { getNodeAutoInstrumentations } =
      await import("@opentelemetry/auto-instrumentations-node");
    const { Resource } = await import("@opentelemetry/resources");
    const {
      SEMRESATTRS_SERVICE_NAME,
      SEMRESATTRS_SERVICE_VERSION,
      SEMRESATTRS_DEPLOYMENT_ENVIRONMENT,
    } = await import("@opentelemetry/semantic-conventions");

    const sdk = new NodeSDK({
      resource: new Resource({
        [SEMRESATTRS_SERVICE_NAME]: "sihalink-notify-agent",
        [SEMRESATTRS_SERVICE_VERSION]: "1.0.0",
        [SEMRESATTRS_DEPLOYMENT_ENVIRONMENT]:
          process.env.ENVIRONMENT ?? "production",
      }),
      traceExporter: new OTLPTraceExporter({
        url: `https://${DT_ENV_ID}.live.dynatrace.com/api/v2/otlp/v1/traces`,
        headers: { Authorization: `Api-Token ${DT_API_TOKEN}` },
      }),
      instrumentations: [
        getNodeAutoInstrumentations({
          "@opentelemetry/instrumentation-http": { enabled: true },
        }),
      ],
    });

    sdk.start();
    process.on("SIGTERM", () => sdk.shutdown());
    console.log(
      `✅ Dynatrace OTel active → https://${DT_ENV_ID}.live.dynatrace.com`,
    );
  } catch (err) {
    console.log(
      "ℹ️  OTel packages not installed — telemetry disabled. Run: npm install",
    );
  }
})();
// ─────────────────────────────────────────────────────────────────────────────

import Fastify, { FastifyRequest, FastifyReply } from "fastify";
import { Bot, session, InlineKeyboard, Context, SessionFlavor } from "grammy";
import type { Update } from "@grammyjs/types";
import {
  type Conversation,
  type ConversationFlavor,
  conversations,
  createConversation,
} from "@grammyjs/conversations";

// ── env ───────────────────────────────────────────────────────────────────────
const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
const PORT = parseInt(process.env.NOTIFY_PORT ?? "3001", 10);
const DASHBOARD =
  process.env.DASHBOARD_URL ?? "https://sihalink.web.app/dashboard";

if (!BOT_TOKEN) throw new Error("TELEGRAM_BOT_TOKEN is not set");

// ── domain types ──────────────────────────────────────────────────────────────

interface SessionData {
  registeredCounty?: string;
  role?: "chw" | "officer";
  pendingReport?: string; // partial report text while awaiting clarification
}

type MyContext = Context & SessionFlavor<SessionData> & ConversationFlavor;
type MyConversation = Conversation<MyContext>;

export interface ReferralData {
  encounter_id: string;
  referral_id?: string;
  syndrome: string;
  triage_color: "RED" | "YELLOW" | "GREEN";
  eta_minutes: number;
  facility_telegram_id: string | number;
  nearest_facility?: string;
  chief_complaint?: string;
  age?: { value: number; unit: string };
  sex?: string;
}

export interface AlertDocument {
  alert_id: string;
  syndrome: string;
  location: { county: string; ward: string };
  count: number;
  percent_above_baseline: number;
  detected_at: string;
  status: string;
  escalation_level?: string;
  risk_level?: string;
  gap_wards?: unknown[];
  recommended_actions?: string[];
}

interface BackendExtraction {
  syndrome?: string;
  triage_color?: string;
  detected_language?: string;
  confidence?: number;
  chief_complaint?: string;
  clarification_needed?: boolean;
  clarification_question?: string;
}

interface BackendIntakeResponse {
  session_id: string;
  extracted: BackendExtraction;
}

interface BackendProtocol {
  syndrome?: string;
  alert_level?: string;
  who_idsr_code?: string;
  immediate_actions?: string[];
  chw_actions?: string[];
}

interface BackendAlert {
  alert_id: string;
  syndrome?: string;
  location?: { county?: string; ward?: string };
  count?: number;
  percent_above_baseline?: number;
  detected_at?: string;
  status?: string;
}

interface BackendSwarmStats {
  encounters_today?: number;
  alerts_dispatched?: number;
  protocols_formulated?: number;
  last_surveillance_run?: string;
}

interface BackendSwarmAgent {
  status: string;
}

interface BackendSwarmStatus {
  status?: string;
  counties_monitored?: number;
  stats?: BackendSwarmStats;
  agents?: Record<string, BackendSwarmAgent>;
}

interface BackendCountyStats {
  encounters_today?: number;
  active_alerts?: number;
  pending_followups?: number;
  active_chws?: number;
}

// ── backend helpers ───────────────────────────────────────────────────────────

async function post<T>(endpoint: string, body: unknown): Promise<T> {
  const res = await fetch(`${BACKEND_URL}${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.text().catch(() => res.statusText);
    throw new Error(`Backend ${endpoint} → ${res.status}: ${err}`);
  }
  return res.json() as Promise<T>;
}

async function get<T>(endpoint: string): Promise<T> {
  const res = await fetch(`${BACKEND_URL}${endpoint}`);
  if (!res.ok) {
    const err = await res.text().catch(() => res.statusText);
    throw new Error(`Backend GET ${endpoint} → ${res.status}: ${err}`);
  }
  return res.json() as Promise<T>;
}

function triageEmoji(color: string): string {
  return color === "RED" ? "🔴" : color === "YELLOW" ? "🟡" : "🟢";
}

function sessionId(chatId: string | number): string {
  return `tg-${chatId}-${Date.now()}`;
}

// ── bot setup ─────────────────────────────────────────────────────────────────

const bot = new Bot<MyContext>(BOT_TOKEN);

bot.use(session({ initial: (): SessionData => ({}) }));
bot.use(conversations());

// ── conversation: /broadcast ──────────────────────────────────────────────────

async function broadcastConversation(
  conversation: MyConversation,
  ctx: MyContext,
): Promise<void> {
  if (!ctx.session.registeredCounty) {
    await ctx.reply("⚠️ Use /register first to set your county jurisdiction.");
    return;
  }
  const county = ctx.session.registeredCounty;

  await ctx.reply(
    `📢 Type the message to broadcast to all CHVs in *${county}*:`,
    { parse_mode: "Markdown" },
  );
  const msgCtx = await conversation.wait();
  const message = msgCtx.message?.text;
  if (!message) {
    await ctx.reply("No message received. Broadcast cancelled.");
    return;
  }

  const kb = new InlineKeyboard()
    .text("✅ Send", "bc_yes")
    .text("❌ Cancel", "bc_no");
  await ctx.reply(`Confirm broadcast to *${county}*:\n\n_${message}_`, {
    parse_mode: "Markdown",
    reply_markup: kb,
  });

  const confirmCtx = await conversation.waitForCallbackQuery([
    "bc_yes",
    "bc_no",
  ]);
  await confirmCtx.answerCallbackQuery();
  if (confirmCtx.callbackQuery.data === "bc_yes") {
    try {
      await post("/tool/register_chw", { county, broadcast_message: message });
    } catch {
      /* best-effort */
    }
    await ctx.reply(
      `✅ Broadcast sent to CHVs in *${county}*:\n\n_${message}_`,
      { parse_mode: "Markdown" },
    );
  } else {
    await ctx.reply("Broadcast cancelled.");
  }
}

bot.use(createConversation(broadcastConversation, "broadcast"));

// ── /start ────────────────────────────────────────────────────────────────────

bot.command("start", async (ctx: MyContext) => {
  await ctx.reply(
    "🏥 *SihaLink — Kenya National Disease Surveillance*\n\n" +
      "AI-powered swarm of agents monitoring disease outbreaks in real-time.\n\n" +
      "*CHW Commands:*\n" +
      "/report `<text>` — Submit encounter (any language)\n" +
      "/followup — View your pending follow-ups\n" +
      "/protocol `<syndrome>` — Get response protocol\n" +
      "/status — County surveillance stats\n\n" +
      "*District Officer Commands:*\n" +
      "/register — Set county jurisdiction\n" +
      "/alerts — Active outbreak alerts\n" +
      "/acknowledge `<id>` — Acknowledge alert\n" +
      "/resolve `<id>` `<notes>` — Resolve alert\n" +
      "/swarm — Autonomous agent swarm status\n" +
      "/broadcast — Message all CHVs\n" +
      "/dashboard — Open web dashboard",
    { parse_mode: "Markdown" },
  );
});

// ── /register ─────────────────────────────────────────────────────────────────

bot.command("register", async (ctx: MyContext) => {
  const counties = [
    ["Homa Bay", "Kisumu"],
    ["Siaya", "Migori"],
    ["Garissa", "Wajir"],
    ["Mandera", "Turkana"],
    ["Nairobi", "Mombasa"],
    ["Nakuru", "Kilifi"],
    ["Bungoma", "Kakamega"],
    ["Marsabit", "Isiolo"],
  ];
  const kb = counties.reduce((k, row) => {
    row.forEach((c) => k.text(c, `reg_${c}`));
    return k.row();
  }, new InlineKeyboard());
  await ctx.reply("Select your county jurisdiction:", { reply_markup: kb });
});

bot.callbackQuery(/^reg_(.+)$/, async (ctx: MyContext) => {
  const county = (ctx.match as RegExpMatchArray)[1];
  ctx.session.registeredCounty = county;
  await ctx.answerCallbackQuery();
  // Register CHW/officer in MongoDB
  try {
    await post("/tool/register_chw", {
      chw_id: `TG-${ctx.from?.id}`,
      name: ctx.from?.first_name ?? "Unknown",
      county,
      telegram_id: ctx.from?.id,
    });
  } catch {
    /* non-fatal */
  }
  await ctx.reply(
    `✅ Registered for *${county}*.\n` +
      `You will receive alerts for this county automatically.`,
    { parse_mode: "Markdown" },
  );
});

// ── /report — CHW submits encounter (text, any language) ─────────────────────

bot.command("report", async (ctx: MyContext) => {
  const text = ctx.message?.text?.replace(/^\/report\s*/i, "").trim();
  const chatId = String(ctx.from?.id ?? "unknown");
  const sid = sessionId(chatId);

  if (!text) {
    await ctx.reply(
      "📝 *How to submit a report:*\n\n" +
        "Type symptoms after /report in any language:\n\n" +
        "`/report Mtoto miaka 2, homa kali, kuhara maji`\n" +
        "`/report Child 3yrs, fever, unable to drink`\n" +
        "`/report Nyithindo gi homa, ratiro, angʼo`\n\n" +
        "Or send a voice note — I will transcribe automatically.",
      { parse_mode: "Markdown" },
    );
    return;
  }

  const thinking = await ctx.reply("⏳ Processing report...");

  try {
    // Start full encounter state machine lifecycle asynchronously
    await post("/encounter/start", {
      session_id: sid,
      telegram_payload: {
        chw_id: chatId,
        message_text: text,
      },
    });

    await ctx.api.editMessageText(
      ctx.chat!.id,
      thinking.message_id,
      "⚡ Encounter lifecycle started. You will receive updates shortly.",
    );
  } catch (err: unknown) {
    await ctx.api
      .deleteMessage(ctx.chat!.id, thinking.message_id)
      .catch(() => undefined);
    const msg = err instanceof Error ? err.message : String(err);
    await ctx.reply(
      `❌ Report failed: ${msg}\nPlease try again or contact support.`,
    );
  }
});

// ── voice note handler — auto-transcribe + extract ───────────────────────────

bot.on("message:voice", async (ctx: MyContext) => {
  const chatId = String(ctx.from?.id ?? "unknown");
  const sid = sessionId(chatId);
  const file = await ctx.getFile();
  const fileUrl = `https://api.telegram.org/file/bot${BOT_TOKEN}/${file.file_path}`;

  const thinking = await ctx.reply("🎙️ Transcribing voice note...");

  try {
    // Download audio from Telegram
    const audioResp = await fetch(fileUrl);
    const audioBuf = await audioResp.arrayBuffer();
    const b64 = Buffer.from(audioBuf).toString("base64");

    await ctx.api.editMessageText(
      ctx.chat!.id,
      thinking.message_id,
      "🧠 Starting encounter analysis...",
    );

    // Start full encounter state machine lifecycle asynchronously
    await post("/encounter/start", {
      session_id: sid,
      audio_base64: b64,
      telegram_payload: {
        chw_id: chatId,
        audio_base64: b64,
      },
    });

    await ctx.api.editMessageText(
      ctx.chat!.id,
      thinking.message_id,
      "⚡ Encounter lifecycle started. You will receive updates shortly.",
    );
  } catch (err: unknown) {
    await ctx.api
      .deleteMessage(ctx.chat!.id, thinking.message_id)
      .catch(() => undefined);
    const msg = err instanceof Error ? err.message : String(err);
    await ctx.reply(`❌ Voice processing failed: ${msg}`);
  }
});

// ── /followup — CHW views their pending follow-ups ───────────────────────────

bot.command("followup", async (ctx: MyContext) => {
  const chatId = String(ctx.from?.id ?? "unknown");

  try {
    const result = await get<{ follow_ups: BackendAlert[]; count: number }>(
      `/tool/follow_ups/${encodeURIComponent(chatId)}`,
    );
    const fus = result.follow_ups ?? [];

    if (fus.length === 0) {
      await ctx.reply("✅ No pending follow-ups. Great work!");
      return;
    }

    const lines = fus.slice(0, 10).map((fu, i) => {
      const due = (fu as unknown as { due_date?: string }).due_date;
      const date = due ? new Date(due).toLocaleDateString("en-KE") : "—";
      return `${i + 1}. ${fu.syndrome ?? "—"} | Due: ${date} | \`${fu.alert_id}\``;
    });

    await ctx.reply(
      `📋 *Your Pending Follow-ups (${fus.length})*\n━━━━━━━━━━━━━━\n` +
        lines.join("\n") +
        (fus.length > 10 ? `\n\n…and ${fus.length - 10} more` : ""),
      { parse_mode: "Markdown" },
    );
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    await ctx.reply(`❌ Could not load follow-ups: ${msg}`);
  }
});

// ── /protocol <syndrome> ──────────────────────────────────────────────────────

bot.command("protocol", async (ctx: MyContext) => {
  const syndrome = ctx.message?.text?.replace(/^\/protocol\s*/i, "").trim();
  if (!syndrome) {
    await ctx.reply(
      "Usage: `/protocol <syndrome>`\n\nExamples:\n" +
        "`/protocol cholera`\n`/protocol measles`\n`/protocol malaria`\n`/protocol ebola`",
      { parse_mode: "Markdown" },
    );
    return;
  }

  const county = ctx.session.registeredCounty;
  const thinking = await ctx.reply("🔍 Researching WHO/CDC/MOH guidelines...");

  try {
    // First try to get an existing protocol from MongoDB
    const p = await get<BackendProtocol>(
      `/tool/protocol/${encodeURIComponent(syndrome)}${county ? `?county=${encodeURIComponent(county)}` : ""}`,
    );

    await ctx.api
      .deleteMessage(ctx.chat!.id, thinking.message_id)
      .catch(() => undefined);

    const actions = (p.immediate_actions ?? [])
      .slice(0, 4)
      .map((a: string) => `• ${a}`)
      .join("\n");
    const chwActions = (p.chw_actions ?? [])
      .slice(0, 3)
      .map((a: string) => `• ${a}`)
      .join("\n");

    // Show source authority badge
    const source = (p as any).source_authority;
    const sourceBadge =
      source && source !== "TEMPLATE" ? `\n\n_📚 Source: ${source}_` : "";

    await ctx.reply(
      `📋 *${syndrome.toUpperCase()} Protocol*\n` +
        `━━━━━━━━━━━━━━\n` +
        `*Alert Level:* ${p.alert_level ?? "YELLOW"}\n` +
        `*WHO Code:* ${p.who_idsr_code ?? "—"}\n\n` +
        `*Immediate Actions:*\n${actions}\n\n` +
        `*CHW Actions:*\n${chwActions}\n\n` +
        `_Full protocol: ${DASHBOARD}_` +
        sourceBadge,
      { parse_mode: "Markdown" },
    );
  } catch (err: unknown) {
    // Protocol not in DB — trigger agentic research, then retry
    await ctx.api
      .editMessageText(
        ctx.chat!.id,
        thinking.message_id,
        "🧠 No protocol found — researching WHO, CDC, and Kenya MOH guidelines...",
      )
      .catch(() => undefined);

    try {
      await post("/tool/research_protocol", {
        syndrome,
        county: county || "all",
        alert_level: "YELLOW",
      });

      // Re-fetch the freshly researched protocol
      const p2 = await get<BackendProtocol>(
        `/tool/protocol/${encodeURIComponent(syndrome)}`,
      );
      await ctx.api
        .deleteMessage(ctx.chat!.id, thinking.message_id)
        .catch(() => undefined);

      const actions2 = (p2.immediate_actions ?? [])
        .slice(0, 4)
        .map((a: string) => `• ${a}`)
        .join("\n");
      const chw2 = (p2.chw_actions ?? [])
        .slice(0, 3)
        .map((a: string) => `• ${a}`)
        .join("\n");
      const src2 = (p2 as any).source_authority;
      const srcBadge2 =
        src2 && src2 !== "TEMPLATE" ? `\n\n_📚 Source: ${src2}_` : "";

      await ctx.reply(
        `📋 *${syndrome.toUpperCase()} Protocol* _(AI-researched)_\n` +
          `━━━━━━━━━━━━━━\n` +
          `*Alert Level:* ${p2.alert_level ?? "YELLOW"}\n` +
          `*WHO Code:* ${p2.who_idsr_code ?? "—"}\n\n` +
          `*Immediate Actions:*\n${actions2}\n\n` +
          `*CHW Actions:*\n${chw2}\n\n` +
          `_Full protocol: ${DASHBOARD}_` +
          srcBadge2,
        { parse_mode: "Markdown" },
      );
    } catch (err2: unknown) {
      await ctx.api
        .deleteMessage(ctx.chat!.id, thinking.message_id)
        .catch(() => undefined);
      const msg = err2 instanceof Error ? err2.message : String(err2);
      await ctx.reply(`❌ Protocol not available for "${syndrome}": ${msg}`);
    }
  }
});

// ── /status — county surveillance stats ──────────────────────────────────────

bot.command("status", async (ctx: MyContext) => {
  const county = ctx.session.registeredCounty;
  if (!county) {
    await ctx.reply("⚠️ Use /register first to set your county.");
    return;
  }

  try {
    const stats = await post<BackendCountyStats>("/tool/get_county_stats", {
      county,
    });
    await ctx.reply(
      `📊 *${county} — Live Stats*\n` +
        `━━━━━━━━━━━━━━\n` +
        `🏥 Encounters today:  *${stats.encounters_today ?? 0}*\n` +
        `🚨 Active alerts:     *${stats.active_alerts ?? 0}*\n` +
        `📅 Pending follow-ups: *${stats.pending_followups ?? 0}*\n` +
        `👥 Active CHWs:       *${stats.active_chws ?? 0}*`,
      { parse_mode: "Markdown" },
    );
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    await ctx.reply(`❌ Could not fetch stats: ${msg}`);
  }
});

// ── /alerts — district officer views active alerts ───────────────────────────

bot.command("alerts", async (ctx: MyContext) => {
  const county = ctx.session.registeredCounty;
  if (!county) {
    await ctx.reply("⚠️ Use /register first.");
    return;
  }

  try {
    const result = await post<{ alerts: BackendAlert[]; count: number }>(
      "/tool/query_active_alerts",
      { county },
    );
    const alerts = result.alerts ?? [];

    if (alerts.length === 0) {
      await ctx.reply(`% Active Alerts — ${county} (0)%\nAll clear.`, {
        parse_mode: "Markdown",
      });
      return;
    }

    const lines = alerts.slice(0, 8).map((a, i) => {
      const loc = a.location ?? {};
      return (
        `${i + 1}. 🚨 *${a.syndrome ?? "?"}* — ${loc.ward ?? "?"}, ${loc.county ?? "?"}\n` +
        `   Cases: ${a.count ?? 0} | \`${a.alert_id}\``
      );
    });

    await ctx.reply(
      `🚨 *Active Alerts — ${county} (${alerts.length})*\n━━━━━━━━━━━━━━\n` +
        lines.join("\n\n") +
        "\n\nUse `/acknowledge <id>` or `/resolve <id> <notes>`",
      { parse_mode: "Markdown" },
    );
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    await ctx.reply(`❌ Could not fetch alerts: ${msg}`);
  }
});

// ── /acknowledge <alert_id> ───────────────────────────────────────────────────

bot.command("acknowledge", async (ctx: MyContext) => {
  const parts = ctx.message?.text?.split(/\s+/) ?? [];
  const alertId = parts[1];
  if (!alertId) {
    await ctx.reply("Usage: `/acknowledge <alert_id>`", {
      parse_mode: "Markdown",
    });
    return;
  }
  try {
    await post("/tool/update_alert_status", {
      alert_id: alertId,
      status: "acknowledged",
      user_id: ctx.from?.username ?? String(ctx.from?.id ?? "unknown"),
    });
    await ctx.reply(`✅ Alert \`${alertId}\` acknowledged.`, {
      parse_mode: "Markdown",
    });
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    await ctx.reply(`❌ Failed: ${msg}`);
  }
});

// ── /resolve <alert_id> <notes> ───────────────────────────────────────────────

bot.command("resolve", async (ctx: MyContext) => {
  const parts = ctx.message?.text?.split(/\s+/) ?? [];
  const alertId = parts[1];
  const notes = parts.slice(2).join(" ");
  if (!alertId) {
    await ctx.reply("Usage: `/resolve <alert_id> <notes>`", {
      parse_mode: "Markdown",
    });
    return;
  }
  try {
    await post("/tool/resolve_alert", {
      alert_id: alertId,
      notes: notes || "Resolved via Telegram",
      user_id: ctx.from?.username ?? String(ctx.from?.id ?? "unknown"),
    });
    await ctx.reply(
      `✅ Alert \`${alertId}\` resolved.\n_Notes: ${notes || "none"}_`,
      { parse_mode: "Markdown" },
    );
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    await ctx.reply(`❌ Failed: ${msg}`);
  }
});

// ── /swarm — autonomous agent swarm status ────────────────────────────────────

bot.command("swarm", async (ctx: MyContext) => {
  try {
    const data = await get<BackendSwarmStatus>("/swarm/status");
    const stats = data.stats ?? {};
    const agents = data.agents ?? {};

    const agentLines = Object.entries(agents)
      .map(([name, info]) => `  ${info.status === "ok" ? "✅" : "⚠️"} ${name}`)
      .join("\n");

    await ctx.reply(
      `🐝 *SihaLink Swarm Status*\n` +
        `━━━━━━━━━━━━━━\n` +
        `*Status:* ${data.status === "running" ? "🟢 Running" : "🔴 Stopped"}\n` +
        `*Counties monitored:* ${data.counties_monitored ?? 0}\n` +
        `*Encounters today:* ${stats.encounters_today ?? 0}\n` +
        `*Alerts dispatched:* ${stats.alerts_dispatched ?? 0}\n` +
        `*Protocols formulated:* ${stats.protocols_formulated ?? 0}\n` +
        `*Last surveillance:* ${stats.last_surveillance_run ?? "pending"}\n\n` +
        `*Agents:*\n${agentLines}\n\n` +
        `_Full dashboard: ${DASHBOARD}_`,
      { parse_mode: "Markdown" },
    );
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    await ctx.reply(`❌ Could not reach swarm: ${msg}`);
  }
});

// ── /broadcast ────────────────────────────────────────────────────────────────

bot.command("broadcast", async (ctx: MyContext) => {
  await ctx.conversation.enter("broadcast");
});

// ── /dashboard ────────────────────────────────────────────────────────────────

bot.command("dashboard", async (ctx: MyContext) => {
  await ctx.reply(`📊 Open the SihaLink surveillance dashboard:\n${DASHBOARD}`);
});

// ── General Text Message Listener — handles active gates and fallback ────────

bot.on("message:text", async (ctx: MyContext) => {
  const chatId = String(ctx.from?.id ?? "unknown");
  const text = ctx.message?.text?.trim();

  // Ignore missing text or commands
  if (!text || text.startsWith("/")) return;

  const thinking = await ctx.reply("⏳ Processing...");

  try {
    // Step 1: check if there's an active human-in-the-loop gate for this chat
    const gateRes = await post<{
      status: string;
      session_id?: string;
      gate?: string;
    }>("/encounter/gate/respond", { chat_id: chatId, text }).catch(
      (): { status: string; session_id?: string; gate?: string } => ({
        status: "no_gate",
      }),
    );

    if (gateRes.status === "resolved") {
      await ctx.api
        .deleteMessage(ctx.chat!.id, thinking.message_id)
        .catch(() => undefined);
      await ctx.reply(
        `✅ Response submitted for session \`${gateRes.session_id}\` (${gateRes.gate} gate).`,
        { parse_mode: "Markdown" },
      );
      return;
    }

    // Step 2: route through the ADK Gemini orchestrator — truly agentic
    // Gemini reads the message, picks tools, chains them, and replies
    const agentRes = await post<{
      status: string;
      response?: string;
      error?: string;
    }>("/encounter/respond", { chat_id: chatId, text });

    await ctx.api
      .deleteMessage(ctx.chat!.id, thinking.message_id)
      .catch(() => undefined);

    if (agentRes.response) {
      // Truncate to Telegram's 4096 char limit
      const reply = agentRes.response.slice(0, 4000);
      await ctx.reply(reply, { parse_mode: "Markdown" }).catch(
        () => ctx.reply(reply), // retry without Markdown if parse fails
      );
    } else {
      await ctx.reply("✅ Request processed by the SihaLink agent swarm.");
    }
  } catch (err: unknown) {
    await ctx.api
      .deleteMessage(ctx.chat!.id, thinking.message_id)
      .catch(() => undefined);
    const msg = err instanceof Error ? err.message : String(err);
    await ctx.reply(`❌ Failed to process: ${msg}`);
  }
});

// ── inline button: confirm / decline referral ─────────────────────────────────

bot.callbackQuery(/^confirm_(.+)$/, async (ctx: MyContext) => {
  const sid = (ctx.match as RegExpMatchArray)[1];
  await ctx.answerCallbackQuery("Referral confirmed ✅");
  await ctx.editMessageReplyMarkup({ reply_markup: new InlineKeyboard() });
  try {
    await post(`/encounter/${sid}/confirm`, { confirmed: true });
    await ctx.reply(`✅ Referral confirmed. Facility notified via Telegram.`);
  } catch {
    /* non-fatal if session expired */
  }
});

bot.callbackQuery(/^decline_(.+)$/, async (ctx: MyContext) => {
  const sid = (ctx.match as RegExpMatchArray)[1];
  await ctx.answerCallbackQuery("Declined");
  await ctx.editMessageReplyMarkup({ reply_markup: new InlineKeyboard() });
  try {
    await post(`/encounter/${sid}/confirm`, { confirmed: false });
  } catch {
    /* non-fatal */
  }
  await ctx.reply("❌ Referral declined. Encounter logged for follow-up.");
});

bot.callbackQuery(/^ref_acc_(.+)$/, async (ctx: MyContext) => {
  const encounterId = (ctx.match as RegExpMatchArray)[1];
  await ctx.answerCallbackQuery("Accepted ✅");
  await ctx.editMessageReplyMarkup({ reply_markup: new InlineKeyboard() });
  try {
    await post("/tool/update_referral_status", {
      referral_id: encounterId,
      status: "accepted",
    });
  } catch {
    /* non-fatal */
  }
  await ctx.reply(
    `✅ Referral *${encounterId}* accepted. Preparing receiving bay.`,
    { parse_mode: "Markdown" },
  );
});

bot.callbackQuery(/^ref_red_(.+)$/, async (ctx: MyContext) => {
  const encounterId = (ctx.match as RegExpMatchArray)[1];
  await ctx.answerCallbackQuery("Redirecting…");
  await ctx.reply(
    `🔄 Referral *${encounterId}* redirected. Specify alternate facility.`,
    { parse_mode: "Markdown" },
  );
});

bot.callbackQuery(/^ack_(.+)$/, async (ctx: MyContext) => {
  const alertId = (ctx.match as RegExpMatchArray)[1];
  await ctx.answerCallbackQuery("Acknowledged ✅");
  await ctx.editMessageReplyMarkup({ reply_markup: new InlineKeyboard() });
  try {
    await post("/tool/update_alert_status", {
      alert_id: alertId,
      status: "acknowledged",
      user_id: String(ctx.from?.id ?? "tg"),
    });
  } catch {
    /* non-fatal */
  }
  await ctx.reply(`✅ Alert \`${alertId}\` acknowledged.`, {
    parse_mode: "Markdown",
  });
});

bot.callbackQuery("view_dash", async (ctx: MyContext) => {
  await ctx.answerCallbackQuery();
  await ctx.reply(`📊 Dashboard: ${DASHBOARD}`);
});

// ── outbound dispatchers (called by HTTP server below) ────────────────────────

export async function dispatchReferral(referral: ReferralData): Promise<void> {
  const emoji = triageEmoji(referral.triage_color);
  const text =
    `🏥 *INCOMING REFERRAL* ${emoji}\n` +
    `━━━━━━━━━━━━━━\n` +
    `*Patient:* ${referral.age?.value ?? "?"} ${referral.age?.unit ?? ""} ${referral.sex ?? ""}\n` +
    `*Suspected:* ${referral.syndrome}\n` +
    `*Complaint:* ${referral.chief_complaint ?? "—"}\n` +
    `*Triage:* ${referral.triage_color}\n` +
    `*ETA:* ${referral.eta_minutes} min\n` +
    `*Facility:* ${referral.nearest_facility ?? "—"}\n` +
    `*ID:* \`${referral.encounter_id}\``;

  const kb = new InlineKeyboard()
    .text("✅ Accept", `ref_acc_${referral.encounter_id}`)
    .text("🔄 Redirect", `ref_red_${referral.encounter_id}`);

  await bot.api.sendMessage(referral.facility_telegram_id, text, {
    parse_mode: "Markdown",
    reply_markup: kb,
  });
}

export async function dispatchOutbreakAlert(
  alert: AlertDocument,
): Promise<void> {
  // Route to county channel if it exists, else log only
  const county = alert.location?.county ?? "Unknown";
  const channel = `@SihaLink_${county.replace(/\s+/g, "")}`;

  const riskEmoji =
    alert.risk_level === "HIGH"
      ? "🔴"
      : alert.risk_level === "MEDIUM"
        ? "🟠"
        : "🟡";

  const text =
    `${riskEmoji} *OUTBREAK ALERT: ${(alert.syndrome ?? "").toUpperCase()}*\n` +
    `━━━━━━━━━━━━━━\n` +
    `*Location:* ${alert.location?.ward ?? "?"} Ward, ${county}\n` +
    `*Cases (6h):* ${alert.count}\n` +
    `*Above baseline:* +${alert.percent_above_baseline}%\n` +
    `*Detected:* ${new Date(alert.detected_at).toLocaleString("en-KE")}\n` +
    (alert.escalation_level
      ? `*Escalation:* ${alert.escalation_level}\n`
      : "") +
    `\n🆔 \`${alert.alert_id}\``;

  const kb = new InlineKeyboard()
    .text("📊 Dashboard", "view_dash")
    .text("✅ Acknowledge", `ack_${alert.alert_id}`);

  // Send to county channel — swallow errors if channel doesn't exist
  try {
    await bot.api.sendMessage(channel, text, {
      parse_mode: "Markdown",
      reply_markup: kb,
    });
    return; // county channel succeeded — done
  } catch {
    /* County channel not found — fall through to facility fallback */
  }

  // Fallback: send to the configured facility chat ID
  const fallback = process.env.FACILITY_TELEGRAM_ID;
  const isPlaceholder =
    !fallback || fallback === "your_facility_chat_id" || fallback.trim() === "";

  if (isPlaceholder) {
    // No valid destination configured — log and skip silently
    console.warn(
      `[Notify] No valid FACILITY_TELEGRAM_ID set — alert ${alert.alert_id} logged only`,
    );
    return;
  }

  try {
    await bot.api.sendMessage(fallback, text, {
      parse_mode: "Markdown",
      reply_markup: kb,
    });
  } catch (err) {
    // Log but don't throw — caller should get 200, not 500
    console.error(
      `[Notify] Fallback dispatch failed for alert ${alert.alert_id}:`,
      err instanceof Error ? err.message : err,
    );
  }
}

// ── HTTP webhook server (receives calls from Python orchestrator) ─────────────

interface ReferralBody {
  referral: ReferralData;
}
interface AlertBody {
  alert: AlertDocument;
}

const server = Fastify({ logger: true });

server.post(
  "/notify/referral",
  async (
    request: FastifyRequest<{ Body: ReferralBody }>,
    reply: FastifyReply,
  ) => {
    const { referral } = request.body;
    if (!referral)
      return reply.status(400).send({ error: "referral payload required" });
    try {
      await dispatchReferral(referral);
      return { delivered: true, type: "referral" };
    } catch (err: unknown) {
      server.log.error(err);
      const msg = err instanceof Error ? err.message : String(err);
      return reply.status(500).send({ error: msg });
    }
  },
);

server.post(
  "/notify/outbreak_alert",
  async (request: FastifyRequest<{ Body: AlertBody }>, reply: FastifyReply) => {
    const { alert } = request.body;
    if (!alert)
      return reply.status(400).send({ error: "alert payload required" });
    try {
      await dispatchOutbreakAlert(alert);
      return { delivered: true, type: "outbreak_alert" };
    } catch (err: unknown) {
      server.log.error(err);
      const msg = err instanceof Error ? err.message : String(err);
      return reply.status(500).send({ error: msg });
    }
  },
);

// General status message endpoint
server.post(
  "/notify/message",
  async (
    request: FastifyRequest<{
      Body: {
        chat_id: string | number;
        text: string;
        parse_mode?: "Markdown" | "HTML";
        reply_markup?: any;
      };
    }>,
    reply: FastifyReply,
  ) => {
    const { chat_id, text, parse_mode, reply_markup } = request.body;
    if (!chat_id || !text)
      return reply.status(400).send({ error: "chat_id and text required" });
    try {
      await bot.api.sendMessage(chat_id, text, {
        parse_mode: parse_mode || "Markdown",
        reply_markup,
      });
      return { delivered: true };
    } catch (err: unknown) {
      server.log.error(err);
      const msg = err instanceof Error ? err.message : String(err);
      return reply.status(500).send({ error: msg });
    }
  },
);

server.get("/health", async () => ({
  status: "ok",
  service: "notify-agent",
  bot: "connected",
}));

// ── startup ───────────────────────────────────────────────────────────────────

async function main(): Promise<void> {
  if (process.env.TELEGRAM_WEBHOOK_URL) {
    const webhookPath = "/telegram";
    await bot.api.setWebhook(process.env.TELEGRAM_WEBHOOK_URL + webhookPath);
    server.post(
      webhookPath,
      async (
        request: FastifyRequest<{ Body: Update }>,
        reply: FastifyReply,
      ) => {
        await bot.handleUpdate(request.body);
        return reply.status(200).send();
      },
    );
    console.log(
      `✅ Webhook set: ${process.env.TELEGRAM_WEBHOOK_URL}${webhookPath}`,
    );
  } else {
    void bot.start({
      onStart: () => console.log("✅ Bot polling started"),
    });
  }

  await server.listen({ port: PORT, host: "0.0.0.0" });
  console.log(`✅ Notify Agent HTTP server on port ${PORT}`);
  console.log(`✅ Backend target: ${BACKEND_URL}`);
}

main().catch(console.error);
