import { NextResponse } from "next/server";
import { getLocalDiagnostics } from "../../../lib/diagnostics.js";

export const runtime = "nodejs";

export async function GET() {
  try {
    return NextResponse.json(await getLocalDiagnostics());
  } catch (error) {
    return NextResponse.json({ error: error.message || "Diagnostics failed" }, { status: 500 });
  }
}
