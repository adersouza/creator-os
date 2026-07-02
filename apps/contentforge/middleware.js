import { NextResponse } from "next/server";
import { authorizeContentForgeRequest } from "./lib/local-api-auth.js";

export function middleware(request) {
  var auth = authorizeContentForgeRequest(request);
  if (auth.ok) return NextResponse.next();
  return NextResponse.json(
    { error: auth.reason },
    {
      status: auth.status || 401,
      headers: { "WWW-Authenticate": "Bearer" },
    }
  );
}

export const config = {
  matcher: ["/api/:path*"],
};
