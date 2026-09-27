export const onRequestPost: PagesFunction<{ LINKS: KVNamespace }> = async (ctx) => {
  const { purchase_id, tx_hash } = await ctx.request.json().catch(() => ({ purchase_id: "", tx_hash: "" }));
  const data = await ctx.env.LINKS.get(`purchase:${purchase_id}`);
  if (!data) return Response.json({ error: "not found" }, { status: 404 });
  const record = JSON.parse(data);
  record.status = "confirmed";
  record.tx_hash = tx_hash;
  record.confirmed_at = Date.now();
  await ctx.env.LINKS.put(`purchase:${purchase_id}`, JSON.stringify(record), { expirationTtl: 60 * 60 * 24 * 30 });
  return Response.json({ status: "confirmed", extra_picks: 2 });
};
