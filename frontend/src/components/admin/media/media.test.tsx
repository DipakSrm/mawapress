import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "@/lib/api";
import { editor, mockSignedIn, renderWithSession, server, setupAdminTest } from "@/test/admin";
import { MediaLibrary } from "./media-library";

vi.mock("next/navigation", async () =>
  (await import("@/test/next-navigation-mock")).navigationMock(),
);

setupAdminTest();
afterEach(() => vi.restoreAllMocks());

const MEDIA = {
  id: "11111111-1111-4111-8111-111111111111",
  url: "/media/a.jpg",
  width: 1200,
  height: 800,
  alt_ne: null,
  alt_en: "A river",
  caption: null,
  variants: { "320": "/media/a-320.webp", "1024": "/media/a-1024.webp" },
};

function mount(items = [MEDIA]) {
  mockSignedIn(editor);
  server.use(
    http.get("*/api/media", () =>
      HttpResponse.json({ items, total: items.length, limit: 24, offset: 0 }),
    ),
  );
  renderWithSession(<MediaLibrary />);
  // applyAccept off: the browser's picker filters by type, but a drop does not.
  return userEvent.setup({ applyAccept: false });
}

const upload = () => screen.findByLabelText("Upload images");

describe("media library uploads", () => {
  it("rejects a wrong type and an oversized file in the browser, without sending them", async () => {
    const spy = vi.spyOn(api, "upload");
    const user = mount();
    await user.upload(await upload(), new File(["x"], "notes.txt", { type: "text/plain" }));
    expect(
      await screen.findByText("Only JPEG, PNG, WebP and GIF images are accepted."),
    ).toBeInTheDocument();

    const big = new File([new Uint8Array(10 * 1024 * 1024 + 1)], "big.jpg", { type: "image/jpeg" });
    await user.upload(await upload(), big);
    expect(await screen.findByText("Files can be at most 10 MB.")).toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled();
  });

  it("shows per-file progress, then the finished state", async () => {
    let finish!: (m: typeof MEDIA) => void;
    vi.spyOn(api, "upload").mockImplementation((_path, _form, opts) => {
      opts?.onProgress?.(0.5);
      return new Promise((resolve) => (finish = resolve as typeof finish));
    });
    const user = mount();
    await user.upload(await upload(), new File(["x"], "photo.jpg", { type: "image/jpeg" }));
    const bar = await screen.findByRole("progressbar", { name: "Uploading photo.jpg" });
    expect(bar).toHaveAttribute("aria-valuenow", "50");
    finish(MEDIA);
    expect(await screen.findByText("Uploaded")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it.each([
    [413, "FILE_TOO_LARGE", "Files can be at most 10 MB."],
    [415, "UNSUPPORTED_MEDIA", "Only JPEG, PNG, WebP and GIF images are accepted."],
    [413, "IMAGE_TOO_LARGE", "Images can be at most 40 megapixels."],
  ])("explains a %s %s from the server", async (status, code, text) => {
    vi.spyOn(api, "upload").mockRejectedValue(new ApiError(status, code, "raw"));
    const user = mount();
    await user.upload(await upload(), new File(["x"], "photo.png", { type: "image/png" }));
    expect(await screen.findByText(text)).toBeInTheDocument();
  });
});

describe("media detail", () => {
  it("saves the alt text when the field loses focus", async () => {
    const bodies: unknown[] = [];
    const user = mount();
    server.use(
      http.patch("*/api/media/:id", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        bodies.push(body);
        return HttpResponse.json({ ...MEDIA, ...body });
      }),
    );
    await user.click(await screen.findByRole("button", { name: /^A river/ }));
    const alt = await screen.findByLabelText("Alt text (नेपाली)");
    await user.type(alt, "नदी");
    expect(bodies).toHaveLength(0);
    await user.tab();
    await waitFor(() => expect(bodies).toEqual([{ alt_ne: "नदी" }]));
  });

  it("saves a pending edit when the sheet is closed with Escape", async () => {
    const bodies: unknown[] = [];
    const user = mount();
    server.use(
      http.patch("*/api/media/:id", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        bodies.push(body);
        return HttpResponse.json({ ...MEDIA, ...body });
      }),
    );
    await user.click(await screen.findByRole("button", { name: /^A river/ }));
    await user.type(await screen.findByLabelText("Caption"), "Koshi in flood");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(bodies).toEqual([{ caption: "Koshi in flood" }]));
    await waitFor(() => expect(screen.queryByLabelText("Caption")).toBeNull());
  });

  it("shows why an image in use cannot be deleted", async () => {
    const user = mount();
    server.use(
      http.delete("*/api/media/:id", () =>
        HttpResponse.json(
          { error: { code: "MEDIA_IN_USE", message: "in use", details: {} } },
          { status: 409 },
        ),
      ),
    );
    await user.click(await screen.findByRole("button", { name: /^A river/ }));
    await user.click(await screen.findByRole("button", { name: "Delete image" }));
    const dialog = await screen.findByRole("dialog", { name: "Delete this image?" });
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/featured image of a post/);
  });

  it("hides delete from reporters", async () => {
    mockSignedIn({ ...editor, role: "reporter" });
    server.use(
      http.get("*/api/media", () =>
        HttpResponse.json({ items: [MEDIA], total: 1, limit: 24, offset: 0 }),
      ),
    );
    renderWithSession(<MediaLibrary />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /^A river/ }));
    await screen.findByLabelText("Alt text (English)");
    expect(screen.queryByRole("button", { name: "Delete image" })).toBeNull();
  });
});
