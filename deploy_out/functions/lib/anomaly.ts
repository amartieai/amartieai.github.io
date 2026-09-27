export interface AnomalyState {
  n: number;
  mean: number[];
  m2: number[];  // sum of squared deviations (Welford)
}

export interface AnomalyResult {
  score: number;
  z: number;
  flagged: boolean;
  freeze: boolean;
  reasons: string[];
}

const FEATURE_NAMES = [
  "utc_hour",
  "ua_length",
  "bot_ua",
  "preview_host",
  "has_oracle_vid",
  "same_ip_as_creator"
];

/**
 * Welford online algorithm for updating mean and variance.
 */
export function updateWelford(state: AnomalyState, features: number[]): AnomalyState {
  const n = state.n + 1;
  const newMean: number[] = [];
  const newM2: number[] = [];

  for (let i = 0; i < FEATURE_NAMES.length; i++) {
    const delta = features[i] - state.mean[i];
    newMean[i] = state.mean[i] + delta / n;
    const delta2 = features[i] - newMean[i];
    newM2[i] = state.m2[i] + delta * delta2;
  }

  return { n, mean: newMean, m2: newM2 };
}

/**
 * Initialize state from KV or with zeros.
 */
export function initState(): AnomalyState {
  return {
    n: 0,
    mean: new Array(FEATURE_NAMES.length).fill(0),
    m2: new Array(FEATURE_NAMES.length).fill(0)
  };
}

/**
 * Compute robust z-score and anomaly score.
 * score = RMS z across dims, clipped at 8.
 * Extra fraud points at z thresholds: 1.5/2.2/3/4 → 8/16/24/40
 */
export function computeAnomaly(state: AnomalyState, features: number[]): AnomalyResult {
  if (state.n < 8) {
    return { score: 0, z: 0, flagged: false, freeze: false, reasons: [] };
  }

  const variances = state.m2.map(m => m / Math.max(state.n - 1, 1));
  const stds = variances.map(v => Math.sqrt(Math.max(v, 1e-10))); // floor to avoid div-by-zero
  const zs = features.map((f, i) => stds[i] > 0 ? (f - state.mean[i]) / stds[i] : 0);

  // RMS z across all dimensions
  const rmsZ = Math.sqrt(zs.reduce((sum, z) => sum + z * z, 0) / zs.length);
  const clippedZ = Math.min(rmsZ, 8);

  // Extra fraud points based on z thresholds
  let extraPoints = 0;
  if (clippedZ >= 4) extraPoints += 40;
  else if (clippedZ >= 3) extraPoints += 24;
  else if (clippedZ >= 2.2) extraPoints += 16;
  else if (clippedZ >= 1.5) extraPoints += 8;

  // Fit only when click already looks clean (score < 30)
  const shouldFit = extraPoints === 0;

  const reasons: string[] = [];
  if (extraPoints >= 40) reasons.push(`anom_z_${clippedZ.toFixed(2)}`);
  if (extraPoints >= 24) reasons.push(`anom_z_${clippedZ.toFixed(2)}`);
  if (extraPoints >= 16) reasons.push(`anom_z_${clippedZ.toFixed(2)}`);
  if (extraPoints >= 8) reasons.push(`anom_z_${clippedZ.toFixed(2)}`);

  return {
    score: extraPoints,
    z: clippedZ,
    flagged: extraPoints >= 8,
    freeze: extraPoints >= 30,
    reasons,
    fit: shouldFit
  };
}

/**
 * Extract features from a request context.
 * Returns 6 features in [0, 1].
 */
export function extractFeatures(
  request: Request,
  ip: string | null,
  creatorIp: string | null
): number[] {
  const url = new URL(request.url);
  const hour = new Date().getUTCHours();
  const ua = request.headers.get("user-agent") || "";

  const features = [
    // 0: UTC hour normalized (0-23 → 0-1)
    hour / 23,
    // 1: UA length normalized (0-200 chars → 0-1, capped)
    Math.min(ua.length / 200, 1),
    // 2: Bot UA (1 if looks like a bot, 0 otherwise)
    isBotUA(ua) ? 1 : 0,
    // 3: Preview host (1 if .pages.dev, 0 otherwise)
    url.hostname.includes(".pages.dev") ? 1 : 0,
    // 4: Has oracle_vid cookie (1 if present)
    request.headers.get("cookie")?.includes("oracle_vid") ? 1 : 0,
    // 5: Same IP as creator
    (ip && creatorIp && ip === creatorIp) ? 1 : 0
  ];

  return features;
}

function isBotUA(ua: string): boolean {
  const botPatterns = [/bot/i, /crawler/i, /spider/i, /scrapy/i, /selenium/i, /playwright/i, /puppeteer/i, /curl/i, /python-requests/i];
  return botPatterns.some(p => p.test(ua));
}
