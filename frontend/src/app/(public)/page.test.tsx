import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import PublicHome from "./page";

describe("public placeholder home", () => {
  it("renders the MAWAPRESS heading and logo", () => {
    render(<PublicHome />);
    expect(screen.getByRole("heading", { name: "MAWAPRESS" })).toBeInTheDocument();
    expect(screen.getByAltText("MAWAPRESS")).toBeInTheDocument();
  });
});
