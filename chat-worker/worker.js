/**
 * Biometrics Analytics Chat Worker
 * Cloudflare Worker — acts as a backend for the chat widget on the
 * biometrics impact page. Bridges the browser to LLM Council and
 * executes Amplitude tool calls on behalf of Claude.
 *
 * Flow:
 *   Browser → POST /chat → Worker → LLM Council (tool loop) → final answer → Browser
 *
 * Env vars (set via wrangler secret put):
 *   AMPLITUDE_API_KEY    — Amplitude project API key
 *   AMPLITUDE_SECRET_KEY — Amplitude project secret key
 *   LLM_KEY              — LLM Council bearer token
 */

const LLM_BASE  = "https://llmproxy.go-yubi.in/chat/completions";
const LLM_MODEL = "bedrock-claude-sonnet-4.6-(US)";
const AMP_BASE  = "https://amplitude.com/api/2";
const MAX_TOOL_ROUNDS = 5;   // safety limit on agentic loops

// ── Known Amplitude events Claude can query ───────────────────────────────────
const KNOWN_EVENTS = `
BIOMETRIC_SETUP_SCREEN_VIEW          — user shown biometrics setup screen
SECURITY_BIOMETRICS_ENABLED          — user enrolled biometrics (≠ first-time signup)
SECURITY_SETUP_SKIPPED               — user tapped "Set Up Later" (deferred)
SECURITY_BIOMETRICS_ENABLE_FAILED    — enrollment OS/backend failure
BIOMETRIC_LOGIN_CLICKED              — user tapped the biometric login button
BIOMETRIC_LOGIN_CHALLENGE_VERIFIED   — biometric login succeeded end-to-end
BIOMETRIC_VERIFY_FAILED              — OS prompt failed (Face ID mismatch, cancel, etc.)
BIOMETRIC_LOGIN_CHALLENGE_FAILED     — backend RSA challenge verification failed
BIOMETRIC_VERIFY_FALLBACK_TO_PIN     — user hit 3-strike limit, fell back to PIN
VERIFY_SECURE_PIN_PAGE_VIEW          — PIN login screen shown (returning user)
VERIFY_SECURE_PIN_FAILED             — wrong PIN entered
VERIFY_SECURE_PIN_SUCCESS            — PIN login succeeded
RESET_PIN_CTA_CLICKED                — user clicked "Forgot PIN"
CREATE_NEW_PIN_PAGE_VIEW             — user entered the PIN reset flow
RESET_PIN_SUCCESS                    — PIN reset completed successfully
RESET_PIN_FAILED                     — PIN reset failed
SIGNIN_PAGE_VIEW                     — signin / login page viewed
VERIFY_OTP_SUCCESS                   — OTP verified (= completed login via OTP)
SETUP_SECURE_PIN_SUCCESS             — new user signup completed (first-time PIN setup only)
`;

// ── System prompt ─────────────────────────────────────────────────────────────
const SYSTEM_PROMPT = `You are an expert product analytics assistant for Aspero (formerly Yubi), a retail bonds/fixed-income investment platform in India.

You are embedded in the Biometrics Feature Launch Impact dashboard. You can answer questions using pre-computed data in your context AND by querying Amplitude in real-time using the query_amplitude tool.

LAUNCH CONTEXT:
- Biometrics (Face ID / Fingerprint) launched April 20, 2026
- Replaces the PIN step that comes after OTP verification for returning users
- RSA-2048 key pair: private key on device (Android Keystore / iOS Keychain), public key registered with backend
- Remote Config: enableBiometricSetup (default true), biometricSetupDeferralDays (default 3)
- iOS bug fixed April 28, 2026 (Face ID OS failure rate was ~70%+)

PRE-COMPUTED SUMMARY (Apr 20–28, 9 days post-launch):
- Setup screen shown: 2,893 | Enrolled: 1,976 (68.3%) | Deferred: 839 | Failed: 199
- Bio login attempts: 1,296 | Verified: 786 (60.6%) | OS failed: 454 (35%) | Backend failed: 24
- iOS login success: 26.7% | Android login success: 65.3%
- Forgot PIN rate dropped: 101.4 → 51.7 per 1000 PIN views (-49%) post-launch
- Forgot PIN clicks/day: 25.1 → 19.6 (-22%)

AVAILABLE AMPLITUDE EVENTS YOU CAN QUERY:
${KNOWN_EVENTS}

DATE RANGES TO KNOW:
- Before launch: 20260324 – 20260419 (27 days)
- After launch:  20260420 – today (use 20260428 as safe "yesterday")
- Biometrics cohort (enrolled Apr 20-23): use these as start/end for cohort analysis

TOOL USAGE RULES:
- Use the tool when the user asks for data not in your context above
- For cohort comparisons, make multiple tool calls (one per cohort)
- Always explain what you queried and interpret the numbers, don't just dump raw data
- Be concise. Lead with the key number, then explain.
- If a query returns zeros, mention that the event may not exist in the date range
`;

// ── Tool definition (OpenAI format) ──────────────────────────────────────────
const TOOLS = [
  {
    type: "function",
    function: {
      name: "query_amplitude",
      description: `Query Amplitude analytics. Use for any data question not already answered by your context.
Supported query_types:
  "total"     — single number: total event count over the date range
  "daily"     — array of daily counts (dates + values)
  "funnel"    — ordered step completion counts (pass 2-4 events in order)
  "platform"  — total counts split by iOS vs Android (pass one event)`,
      parameters: {
        type: "object",
        properties: {
          query_type: {
            type: "string",
            enum: ["total", "daily", "funnel", "platform"],
            description: "Type of Amplitude query to run",
          },
          events: {
            type: "array",
            items: { type: "string" },
            description: "Event name(s). For funnel: ordered list of 2-4 steps. For others: single event in array.",
          },
          start_date: {
            type: "string",
            description: "Start date YYYYMMDD e.g. 20260420",
          },
          end_date: {
            type: "string",
            description: "End date YYYYMMDD e.g. 20260428",
          },
        },
        required: ["query_type", "events", "start_date", "end_date"],
      },
    },
  },
];

// ── Amplitude queries ─────────────────────────────────────────────────────────
async function amplitudeAuth(env) {
  const token = btoa(`${env.AMPLITUDE_API_KEY}:${env.AMPLITUDE_SECRET_KEY}`);
  return { Authorization: `Basic ${token}`, Accept: "application/json" };
}

async function ampSegmentation(event, start, end, groupBy, headers) {
  const e = JSON.stringify({ event_type: event });
  const params = new URLSearchParams({ e, start, end, m: "totals", i: "1" });
  if (groupBy) params.set("g", groupBy);
  const r = await fetch(`${AMP_BASE}/events/segmentation?${params}`, { headers });
  if (!r.ok) throw new Error(`Amplitude HTTP ${r.status}`);
  return (await r.json()).data || {};
}

async function ampFunnel(events, start, end, headers) {
  const params = new URLSearchParams({ start, end });
  events.forEach(e => params.append("e", JSON.stringify({ event_type: e })));
  const r = await fetch(`${AMP_BASE}/funnels?${params}`, { headers });
  if (!r.ok) throw new Error(`Amplitude funnel HTTP ${r.status}`);
  const data = (await r.json()).data || [];
  return data[0]?.cumulativeRaw || [];
}

async function runAmplitudeTool({ query_type, events, start_date, end_date }, env) {
  const headers = await amplitudeAuth(env);

  if (query_type === "total") {
    const data = await ampSegmentation(events[0], start_date, end_date, null, headers);
    const total = (data.series?.[0] || []).reduce((s, v) => s + v, 0);
    return { event: events[0], total, start: start_date, end: end_date };
  }

  if (query_type === "daily") {
    const data = await ampSegmentation(events[0], start_date, end_date, null, headers);
    const dates  = data.xValues || [];
    const values = data.series?.[0] || [];
    return { event: events[0], dates, values };
  }

  if (query_type === "funnel") {
    const counts = await ampFunnel(events, start_date, end_date, headers);
    return {
      steps: events.map((e, i) => ({ event: e, count: counts[i] || 0 })),
      conversion_rates: events.map((_, i) =>
        i === 0 ? 100 : counts[0] ? +((counts[i] / counts[0]) * 100).toFixed(1) : 0
      ),
    };
  }

  if (query_type === "platform") {
    const data = await ampSegmentation(events[0], start_date, end_date, "platform", headers);
    const labels = data.seriesLabels || [];
    const series = data.series || [];
    const result = {};
    labels.forEach((lbl, i) => {
      const plat = Array.isArray(lbl) ? lbl[0] : lbl;
      result[plat] = (series[i] || []).reduce((s, v) => s + v, 0);
    });
    return { event: events[0], by_platform: result };
  }

  throw new Error(`Unknown query_type: ${query_type}`);
}

// ── LLM call (one turn) ───────────────────────────────────────────────────────
async function llmCall(messages, env) {
  const r = await fetch(LLM_BASE, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.LLM_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: LLM_MODEL,
      max_tokens: 1024,
      messages,
      tools: TOOLS,
      tool_choice: "auto",
    }),
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(`LLM Council HTTP ${r.status}: ${t.slice(0, 200)}`);
  }
  return r.json();
}

// ── Agentic tool loop ─────────────────────────────────────────────────────────
async function agentLoop(userMessages, env) {
  const messages = [
    { role: "system", content: SYSTEM_PROMPT },
    ...userMessages,
  ];

  for (let round = 0; round < MAX_TOOL_ROUNDS; round++) {
    const resp = await llmCall(messages, env);
    const choice = resp.choices?.[0];
    const msg    = choice?.message;

    // No tool call → done
    if (choice?.finish_reason !== "tool_calls" || !msg?.tool_calls?.length) {
      return msg?.content || "(empty response)";
    }

    // Append assistant message with tool_calls
    messages.push({ role: "assistant", content: msg.content || null, tool_calls: msg.tool_calls });

    // Execute each tool call and append results
    for (const tc of msg.tool_calls) {
      let result;
      try {
        const args = JSON.parse(tc.function.arguments);
        result = await runAmplitudeTool(args, env);
      } catch (e) {
        result = { error: e.message };
      }
      messages.push({
        role: "tool",
        tool_call_id: tc.id,
        content: JSON.stringify(result),
      });
    }
  }

  return "Reached maximum tool call limit. Please try a more specific question.";
}

// ── Request handler ────────────────────────────────────────────────────────────
export default {
  async fetch(request, env) {
    // CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "POST, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type",
        },
      });
    }

    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }

    try {
      const { messages } = await request.json();
      if (!Array.isArray(messages) || messages.length === 0) {
        return new Response(JSON.stringify({ error: "messages array required" }), {
          status: 400,
          headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
        });
      }

      const answer = await agentLoop(messages, env);

      return new Response(JSON.stringify({ reply: answer }), {
        headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
      });
    } catch (e) {
      return new Response(JSON.stringify({ error: e.message }), {
        status: 500,
        headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
      });
    }
  },
};
