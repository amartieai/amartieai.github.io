export const onRequestGet: PagesFunction<{ LINKS: KVNamespace }> = async (ctx) => {
  const refId = ctx.request.url.split('?ref=').pop() || '';
  const data = await ctx.env.LINKS.get(`ref:${refId}`);
  if (!data) return Response.json({ error: "not found" }, { status: 404 });
  return Response.json(JSON.parse(data));
};
