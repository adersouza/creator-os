import { NextResponse } from "next/server";
import { authorizeApiRequest } from "../../../../../lib/auth.js";
import { submitDecision } from "../../../../../lib/inbox.js";

export const dynamic = "force-dynamic";

export async function POST(request, { params }) {
  var auth = authorizeApiRequest(request);
  if (!auth.ok) return NextResponse.json({ reason: auth.reason }, { status: auth.status });
  var { assetId } = await params;
  var body = await request.json().catch(function () {
    return {};
  });
  var outcome = await submitDecision({
    assetId,
    decision: body.decision,
    reason: body.reason,
  });
  if (!outcome.ok) {
    return NextResponse.json({ reason: outcome.reason }, { status: outcome.status });
  }
  return NextResponse.json(outcome.result);
}
