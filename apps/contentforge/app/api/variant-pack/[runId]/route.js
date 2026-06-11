import { NextResponse } from "next/server";
import { loadVariantPack } from "../../../../lib/variant-pack.js";

export const runtime = "nodejs";

export async function GET(_request, { params }) {
  try {
    var routeParams = await params;
    var report = await loadVariantPack(routeParams.runId);
    return NextResponse.json(report);
  } catch (err) {
    return NextResponse.json({ error: err.message }, { status: 404 });
  }
}
