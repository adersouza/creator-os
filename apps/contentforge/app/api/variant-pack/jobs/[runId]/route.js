import { NextResponse } from "next/server";
import { loadVariantPackJob } from "../../../../../lib/variant-pack-jobs.js";

export const runtime = "nodejs";

export async function GET(_request, { params }) {
  var routeParams = await params;
  var job = await loadVariantPackJob(routeParams.runId);
  if (!job) {
    return NextResponse.json({ error: "Variant pack job not found" }, { status: 404 });
  }
  return NextResponse.json(job);
}
