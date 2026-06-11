import { NextResponse } from "next/server";
import { loadVariantPack } from "../../../../../lib/variant-pack.js";

export const runtime = "nodejs";

export async function GET(_request, { params }) {
  try {
    var routeParams = await params;
    var report = await loadVariantPack(routeParams.runId);
    return NextResponse.json({
      schema: report.schema || "contentforge.variant_pack.v1",
      runId: report.runId,
      source: report.source,
      sourcePath: report.sourcePath,
      outputDir: report.outputDir,
      manifestPath: report.manifestPath,
      manifestUrl: report.manifestUrl,
      request: report.request,
      variationPreset: report.variationPreset,
      recipeList: report.recipeList || [],
      plannedFamilies: report.plannedFamilies || [],
      operatorSummary: report.operatorSummary,
      results: report.results || [],
      createdAt: report.createdAt,
    });
  } catch (err) {
    return NextResponse.json({ error: err.message }, { status: 404 });
  }
}
