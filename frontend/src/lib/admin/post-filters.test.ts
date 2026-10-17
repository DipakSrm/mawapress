import { describe, expect, it } from "vitest";
import { filtersToApiQuery, filtersToSearch, parseFilters } from "./post-filters";

const parse = (qs: string) => parseFilters(new URLSearchParams(qs));

describe("post filters", () => {
  it("parses valid values and ignores junk", () => {
    expect(parse("status=draft&category=3&author=u1&lang=en&q=%20flood%20&page=4")).toEqual({
      status: "draft",
      category: 3,
      author: "u1",
      locale: "en",
      q: "flood",
      page: 4,
    });
    expect(parse("status=bogus&category=abc&lang=fr&page=-2")).toEqual({
      status: undefined,
      category: undefined,
      author: undefined,
      locale: undefined,
      q: "",
      page: 1,
    });
  });

  it("round-trips through the URL and omits defaults", () => {
    expect(filtersToSearch(parse(""))).toBe("");
    const qs = "status=in_review&category=2&lang=ne&q=rain&page=2";
    expect(filtersToSearch(parse(qs))).toBe(qs);
  });

  it("maps page to limit/offset", () => {
    expect(filtersToApiQuery(parse("page=3&category=5"))).toMatchObject({
      limit: 20,
      offset: 40,
      category_id: 5,
    });
  });
});
