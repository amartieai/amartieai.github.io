export const onRequestPost: PagesFunction<{ LINKS: KVNamespace }> = async (ctx) => {
  // Purchase gate: check purchase:enabled in KV
// BUILD: 2026-09-27 v3
  const enabled = await ctx.env.LINKS.get("purchase:enabled");
  if (enabled !== "true") {
    return new Response("Disabled", { status: 403 });
  }
  const { email, currency } = await ctx.request.json().catch(() => ({ email: "", currency: "BTC" }));
  const id = crypto.randomUUID().slice(0, 8);
  await ctx.env.LINKS.put(`purchase:${id}`, JSON.stringify({ email, currency, status: "pending", created: Date.now() }), {
    expirationTtl: 60 * 60 * 24,
  });
  return Response.json({ purchase_id: id, status: "pending" });
};
