export const onRequestPost: PagesFunction<{ LINKS: KVNamespace }> = async (ctx) => {
  const { email } = await ctx.request.json().catch(() => ({ email: "" }));
  const id = crypto.randomUUID().slice(0, 8);
  // Build the link from THIS request's host, not a hardcoded domain
  const url = new URL(ctx.request.url);
  const proto = url.protocol; // https://
  const host = url.host;     // e.g. 08349050.oracle-system.pages.dev
  const origin = `${proto}//${host}`;
  const link = `${origin}/?ref=${id}`;
  await ctx.env.LINKS.put(`ref:${id}`, JSON.stringify({ email, n: 0 }), {
    expirationTtl: 60 * 60 * 24 * 90,
  });
  const total = await ctx.env.LINKS.get(`total_free_picks`);
  return Response.json({ link, total_free_picks: total ? parseInt(total) : 0 });
};
