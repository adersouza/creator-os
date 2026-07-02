import { NextResponse } from "next/server";
import { authorizeApiRequest } from "./lib/auth.js";

export function proxy(request) {
  var result = authorizeApiRequest(request);
  if (result.ok) return NextResponse.next();
  return NextResponse.json(
    { error: result.reason },
    { status: result.status, headers: { "WWW-Authenticate": "Bearer" } },
  );
}

export const config = {
  matcher: "/api/:path*",
};
