import createClient from "openapi-fetch";
import type { paths } from "./schema";

/** Typed API client. Browser calls go to the BFF proxy, which adds the API key server-side. */
export const api = createClient<paths>({ baseUrl: "/api/proxy" });
