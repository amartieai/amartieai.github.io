import { computeAnomaly, extractFeatures, updateWelford, initState, type AnomalyState } from "../lib/anomaly.ts";

export const onRequestPost: PagesFunction<{ LINKS: KVNamespace }> = async (ctx) => {
  const { ref, src } = await ctx.request.json().catch(() => ({ ref: "", src: "" }));
  const ip = ctx.request.headers.get("cf-connecting-ip") || 
             ctx.request.headers.get("x-forwarded-for") || 
             "unknown";
  const hostname = new URL(ctx.request.url).hostname;

  // Get or init the anomaly state for this ref
  const stateKey = `anom:${ref}`;
  let state: AnomalyState;
  const existing = await ctx.env.LINKS.get(stateKey);
  if (existing) {
    state = JSON.parse(existing);
  } else {
    state = initState();
  }

  // Extract features from this request
  const features = extractFeatures(ctx.request, ip, null);

  // Compute anomaly score BEFORE fitting
  const result = computeAnomaly(state, features);

  // Check verdict
  const verdict = result.score >= 70 ? "FREEZE" : result.score >= 30 ? "IGNORE" : "CREDIT";

  if (verdict === "FREEZE") {
    // Write WAE point for freeze
    try {
      if(ctx.env.AE)ctx.env.AE.writeDataPoint({
        blobs: [ref, verdict, hostname, result.reasons[0] || ""],
        doubles: [1, result.score, result.z],
        indexes: [ref],
      });
    } catch(e) { /* fire-and-forget */ }
    return Response.json({ n: state.n, verdict: "FREEZE", reason: result.reasons[0] || "anom_z_" + result.z.toFixed(2) }, { status: 403 });
  }

  if (verdict === "IGNORE") {
    // Still record the click but don't credit
    const data = await ctx.env.LINKS.get(`ref:${ref}`);
    const record = data ? JSON.parse(data) : { n: 0 };
    record.n = (record.n || 0) + 1;
    await ctx.env.LINKS.put(`ref:${ref}`, JSON.stringify(record), { expirationTtl: 60 * 60 * 24 * 90 });
    const newState = updateWelford(state, features);
    await ctx.env.LINKS.put(stateKey, JSON.stringify(newState), { expirationTtl: 60 * 60 * 24 * 90 });
    // Write WAE point (fire-and-forget)
    try {
      if(ctx.env.AE)ctx.env.AE.writeDataPoint({
        blobs: [ref, verdict, hostname, result.reasons[0] || ""],
        doubles: [1, result.score, result.z],
        indexes: [ref],
      });
    } catch(e) { /* fire-and-forget */ }
    return Response.json({ n: record.n, verdict: "IGNORE", reason: result.reasons[0] || "anom_z_" + result.z.toFixed(2) });
  }

  // CREDIT — increment the click counter
  const data = await ctx.env.LINKS.get(`ref:${ref}`);
  const record = data ? JSON.parse(data) : { n: 0 };
  record.n = (record.n || 0) + 1;
  await ctx.env.LINKS.put(`ref:${ref}`, JSON.stringify(record), { expirationTtl: 60 * 60 * 24 * 90 });

  // Fit the model ONLY if the click already looks clean
  if (result.fit) {
    const newState = updateWelford(state, features);
    await ctx.env.LINKS.put(stateKey, JSON.stringify(newState), { expirationTtl: 60 * 60 * 24 * 90 });
  }

  // Write WAE point (fire-and-forget, do not await)
  try {
    if(ctx.env.AE)ctx.env.AE.writeDataPoint({
      blobs: [ref, verdict, hostname, result.reasons[0] || ""],
      doubles: [1, result.score, result.z],
      indexes: [ref],
    });
  } catch(e) { /* fire-and-forget */ }

  // Build response
  const response: Record<string, unknown> = { n: record.n };
  if (result.flagged) {
    response.reason = result.reasons[0] || "anom_z_" + result.z.toFixed(2);
  }

  return Response.json(response);
};
