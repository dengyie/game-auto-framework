export async function onRequest(context) {
  const url = new URL(context.request.url);
  const targetBase = context.env.BACKEND_URL || "http://45.202.199.205:8000";
  const targetUrl = new URL(url.pathname + url.search, targetBase);

  const requestHeaders = new Headers(context.request.headers);
  requestHeaders.set("Host", "45.202.199.205:8000");
  requestHeaders.set("X-Forwarded-Host", url.host);
  requestHeaders.set("X-Forwarded-Proto", url.protocol.replace(":", ""));

  const init = {
    method: context.request.method,
    headers: requestHeaders,
    redirect: "follow",
  };

  if (context.request.method !== "GET" && context.request.method !== "HEAD") {
    init.body = context.request.body;
    init.duplex = "half";
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
