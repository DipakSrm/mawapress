import { describe, expect, it } from "vitest";
import { loginUrl, safeNextPath } from "./next-path";

describe("safeNextPath", () => {
  it.each([
    ["/admin", "/admin"],
    ["/admin/posts", "/admin/posts"],
    ["/admin/posts?status=draft", "/admin/posts?status=draft"],
    ["/admin?x=1", "/admin?x=1"],
    ["/admin#top", "/admin#top"],
  ])("accepts %s", (input, expected) => {
    expect(safeNextPath(input)).toBe(expected);
  });

  it.each([
    "https://x",
    "//evil.example",
    "/\\x",
    "/admin\\x",
    "/adminfoo",
    "/administrator",
    "/admin/login",
    "/admin/login?next=/admin",
    "/admin/login#x",
    "/admin/login/",
    "/other",
    "",
    null,
    undefined,
  ])("falls back to /admin for %s", (input) => {
    expect(safeNextPath(input)).toBe("/admin");
  });

  it("loginUrl omits next for the default target", () => {
    expect(loginUrl("/admin")).toBe("/admin/login");
    expect(loginUrl("/admin/posts?a=1")).toBe("/admin/login?next=%2Fadmin%2Fposts%3Fa%3D1");
  });
});
