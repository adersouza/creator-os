function truthy(value) {
  return value && ["1", "true", "yes", "on"].includes(String(value).trim().toLowerCase());
}

function loopbackHost(value) {
  var host = String(value || "").replace(/^\[/, "").replace(/\]$/, "").split(":")[0];
  return host === "localhost" || host === "::1" || host === "127.0.0.1";
}

function requestHost(request) {
  return request.headers.get("host") || new URL(request.url).host;
}

function originIsLocal(request) {
  var origin = request.headers.get("origin");
  return !origin || loopbackHost(new URL(origin).hostname);
}

export function authorizeContentForgeRequest(request, env = process.env) {
  var token = env.CREATOR_OS_API_TOKEN;
  if (token) {
    if (request.headers.get("authorization") === "Bearer " + token) {
      return { ok: true };
    }
    return { ok: false, status: 401, reason: "missing_or_invalid_api_token" };
  }
  if (
    truthy(env.ALLOW_INSECURE_LOCAL) &&
    loopbackHost(requestHost(request)) &&
    originIsLocal(request)
  ) {
    return { ok: true };
  }
  return { ok: false, status: 401, reason: "creator_os_api_token_required" };
}
