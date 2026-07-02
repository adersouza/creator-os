import { NextResponse } from "next/server";
import { authorizeApiRequest } from "../../../lib/auth.js";
import { collectInbox } from "../../../lib/inbox.js";

export const dynamic = "force-dynamic";

export async function GET(request) {
  var auth = authorizeApiRequest(request);
  if (!auth.ok) return NextResponse.json({ reason: auth.reason }, { status: auth.status });
  try {
    return NextResponse.json(collectInbox());
  } catch (error) {
    return NextResponse.json({ error: error.message || "inbox failed" }, { status: 500 });
  }
}
