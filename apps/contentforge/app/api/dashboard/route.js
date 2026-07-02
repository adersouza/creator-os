import { NextResponse } from "next/server";
import { collectDashboard } from "../../../lib/dashboard-data.js";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    return NextResponse.json(await collectDashboard());
  } catch (error) {
    return NextResponse.json({ error: error.message || "dashboard failed" }, { status: 500 });
  }
}
