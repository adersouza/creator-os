import { NextResponse } from "next/server";
import { authorizeApiRequest } from "../../../../lib/auth.js";
import { collectInboxHistory } from "../../../../lib/inbox.js";

export const dynamic = "force-dynamic";

export async function GET(request) {
  var auth = authorizeApiRequest(request);
  if (!auth.ok) return NextResponse.json({ reason: auth.reason }, { status: auth.status });
  try {
    return NextResponse.json(collectInboxHistory());
  } catch (error) {
    return NextResponse.json({ error: error.message || "history failed" }, { status: 500 });
  }
}
