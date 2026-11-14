import { describe, expect, it } from "vitest";
import { ApiError, request, setToken } from "../lib/api";

describe("the typed client", () => {
  it("sends the bearer token and turns refusals into errors with the platform's message", async () => {
    setToken("tok");
    let auth = "";
    const fake = (async (_u: string, init: RequestInit) => {
      auth = (init.headers as Record<string, string>).Authorization;
      return new Response('{"error":"workspace administrators only"}', { status: 403 });
    }) as unknown as typeof fetch;
    await expect(request("POST", "/platform/x", {}, fake)).rejects.toMatchObject({ status: 403,
      message: "workspace administrators only" });
    expect(auth).toBe("Bearer tok");
    await expect(request("GET", "/platform/x", undefined, fake)).rejects.toBeInstanceOf(ApiError);
  });
});
