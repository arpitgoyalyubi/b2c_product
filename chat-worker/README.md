# Biometrics Chat Worker

Cloudflare Worker that powers the AI chat widget on the biometrics impact page.

## What it does

- Receives chat messages from the browser
- Runs a Claude tool-use loop via LLM Council
- Executes live Amplitude queries when Claude needs data not in its context
- Returns the final answer to the browser

Claude can answer questions like "compare cohort A vs B retention" or "what is the forgot PIN rate this week" by querying Amplitude in real time — not just pre-computed numbers.

## Deploy (one-time, ~5 mins)

```bash
cd chat-worker

# 1. Install Wrangler if you don't have it
npm install -g wrangler

# 2. Login to Cloudflare
wrangler login

# 3. Set secrets (keys never go in code)
wrangler secret put AMPLITUDE_API_KEY
# paste: 80ba75db8682a36264f7eb8becb6107b

wrangler secret put AMPLITUDE_SECRET_KEY
# paste: a81c9a7884de00ab43e4577fe039fb6e

wrangler secret put LLM_KEY
# paste: sk-5wJPukqGUr_yz7c2JORgtA

# 4. Deploy
wrangler deploy
# → prints: https://biometrics-chat.YOUR-SUBDOMAIN.workers.dev
```

## Activate in the dashboard

After deploy, copy the workers.dev URL and update this line in `biometrics-impact.html`:

```js
const WORKER_URL = 'https://biometrics-chat.YOUR-SUBDOMAIN.workers.dev';
```

Then commit + push. The chat widget will now route through the Worker and can answer any Amplitude query.

## How the tool loop works

```
User asks: "compare forgot PIN rate for enrolled vs deferred users"
  → Worker calls Claude with tools
  → Claude calls query_amplitude({query_type:"funnel", events:[...], ...})
  → Worker queries Amplitude, returns numbers
  → Claude calls query_amplitude again for second cohort
  → Worker returns second set of numbers
  → Claude formulates final answer with both sets of data
  → Worker returns text to browser
```

Max 5 tool rounds per question (safety limit).
