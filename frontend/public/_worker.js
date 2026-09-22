export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // If request is for an API endpoint or health check, proxy to DGN Links VPS backend
    if (url.pathname.startsWith("/api/") || url.pathname === "/health") {
      const backendUrl = env.BACKEND_URL || "https://game.mangoqwq.com";
      const targetUrl = new URL(url.pathname + url.search, backendUrl);

      const requestHeaders = new Headers(request.headers);
      requestHeaders.set("Host", "game.mangoqwq.com");
      requestHeaders.set("X-Forwarded-Host", url.host);
      requestHeaders.set("X-Forwarded-Proto", url.protocol.replace(":", ""));

      const init = {
        method: request.method,
        headers: requestHeaders,
        redirect: "follow",
      };

      if (request.method !== "GET" && request.method !== "HEAD") {
        init.body = request.body;
      }

      try {
        const response = await fetch(targetUrl.toString(), init);
        const responseHeaders = new Headers(response.headers);
        responseHeaders.set("Access-Control-Allow-Origin", "*");
        responseHeaders.set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
        responseHeaders.set("Access-Control-Allow-Headers", "*");

        return new Response(response.body, {
          status: response.status,
          statusText: response.statusText,
          headers: responseHeaders,
        });
      } catch (err) {
        return new Response(JSON.stringify({ error: "Backend proxy unreachable", details: String(err) }), {
          status: 502,
          headers: { "Content-Type": "application/json" }
        });
      }
    }

    // If requesting /dashboard or root, serve index.html
    if (url.pathname === "/dashboard") {
      return env.ASSETS.fetch(new URL("/", request.url));
    }

    // Otherwise, serve static assets
    return env.ASSETS.fetch(request);
  }
};
