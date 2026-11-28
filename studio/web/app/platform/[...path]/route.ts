import { forward } from "@/lib/forward";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  return forward(req);
}

export async function POST(req: Request) {
  return forward(req);
}
