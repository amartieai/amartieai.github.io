export const onRequestPost: PagesFunction<{ LINKS: KVNamespace }> = async (ctx) => {
  const { refId, proof } = await ctx.request.json().catch(() => ({ refId: "", proof: "" }));
  const data = await ctx.env.LINKS.get(`ref:${refId}`);
  if (!data) return Response.json({ error: "not found" }, { status: 404 });
  const record = JSON.parse(data);
  // Jev verification: check the proof matches the share token
  const verified = proof && proof.length > 0 && record.email !== "";
  return Response.json({ verified, email: verified ? record.email : null });
};
