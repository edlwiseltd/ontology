import type { Metadata } from "next";
import RuntimeApp from "@/runtime/RuntimeApp";

// The application runtime, at its own address. It is not a screen of Studio: it has its own sign-in and renders
// whatever application the Engine has for this use case and this caller.
export const metadata: Metadata = { title: "Autology application", description: "A business application rendered from a governed solution" };

export default async function Page({ params }: { params: Promise<{ workspace: string; useCase: string }> }) {
  const { workspace, useCase } = await params;
  return <RuntimeApp workspace={workspace} useCase={useCase} />;
}
