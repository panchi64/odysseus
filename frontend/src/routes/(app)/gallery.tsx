import { RequirePrivilege } from "~/lib/guards";
import { GalleryScreen } from "~/features/gallery";

export default function GalleryRoute() {
  return (
    <RequirePrivilege privilege="gallery">
      <GalleryScreen />
    </RequirePrivilege>
  );
}
