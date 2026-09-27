export const onRequest: PagesFunction = async (ctx) => {
  const url = new URL(ctx.request.url);
  const path = url.pathname;

  // Block GET on all /api/* routes (POST only)
  if (path.startsWith("/api/") && ctx.request.method !== "POST") {
    return new Response("POST only", { status: 405, headers: { allow: "POST" } });
  }

  // Block purchase, confirm-purchase, and JEV on ALL hosts
  // These routes are local-only until a real domain and settlement are in place
  if (path === "/api/purchase" || path === "/api/confirm-purchase") {
    return new Response("Disabled", { status: 403 });
  }
  if (path === "/api/jev-verify-share") {
    return new Response("Local only", { status: 403 });
  }

  return ctx.next();
};