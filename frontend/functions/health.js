export async function onRequest(context) {
  const targetBase = context.env.BACKEND_URL || "http://45.202.199.205:8000";
  const targetUrl = new URL("/health", targetBase);

  try {
    const response = await fetch(targetUrl.toString());
    return new Response(response.body, {
      status: response.status,
      headers: response.headers
    });
  } catch (err) {
    return new Response(JSON.stringify({ status: "error", details: String(err) }), {
      status: 502,
      headers: { "Content-Type": "application/json" }
    });
  }
}
