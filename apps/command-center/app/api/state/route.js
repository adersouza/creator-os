import { NextResponse } from "next/server";
import { collectState } from "../../../lib/data.js";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    return NextResponse.json(await collectState());
  } catch (error) {
    return NextResponse.json({ error: error.message || "state failed" }, { status: 500 });
  }
}
