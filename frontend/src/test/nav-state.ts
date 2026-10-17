import { vi } from "vitest";

/** Shared fake router state. Kept free of app imports so the next/navigation mock can load it. */
export const router = { replace: vi.fn(), push: vi.fn(), refresh: vi.fn() };
export const nav = { pathname: "/admin", search: "" };
