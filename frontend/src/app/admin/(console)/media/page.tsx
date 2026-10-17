import type { Metadata } from "next";
import { MediaLibrary } from "@/components/admin/media/media-library";

export const metadata: Metadata = { title: "Media" };

export default function MediaRoute() {
  return <MediaLibrary />;
}
