/** Ownership of the panel's download control.
 *
 *  The module exists for one property: a component releasing its claim — explicitly or by
 *  being disposed — must not disturb anyone else's. Under the single unowned signal this
 *  replaced, every one of the disposal tests below would have come back null, because any
 *  component's cleanup cleared the whole seam.
 *
 *  Claims are module-level (there is one panel), so each test disposes the roots it opens
 *  and leaves the registry empty for the next.
 */

import { afterEach, describe, expect, test } from "bun:test";
import { createRoot } from "solid-js";
import {
  activeDownload,
  createDownloadSlot,
  type ActiveDownload,
  type DownloadSlot,
} from "./downloadRegistry";

const file = (name: string): ActiveDownload => ({
  name,
  getBlob: async () => new Blob([name]),
});

const open = new Set<() => void>();

/** A component that owns a download slot, with the handle to dispose it. */
function mount(): { arm: DownloadSlot; dispose: () => void } {
  return createRoot((dispose) => {
    open.add(dispose);
    return {
      arm: createDownloadSlot(),
      dispose: () => {
        open.delete(dispose);
        dispose();
      },
    };
  });
}

afterEach(() => {
  for (const dispose of [...open]) dispose();
  open.clear();
});

describe("download claims", () => {
  test("nothing is armed until someone arms it", () => {
    expect(activeDownload()).toBeNull();
    const a = mount();
    expect(activeDownload()).toBeNull();
    a.arm(file("one"));
    expect(activeDownload()?.name).toBe("one");
  });

  test("the most recently armed claim is the one on offer", () => {
    const a = mount();
    const b = mount();
    a.arm(file("a"));
    b.arm(file("b"));
    expect(activeDownload()?.name).toBe("b");
    // Re-arming moves a claim to the front, rather than leaving it where it first
    // landed — the control follows the view that most recently got bytes in hand.
    a.arm(file("a2"));
    expect(activeDownload()?.name).toBe("a2");
  });

  test("disposing an owner releases only its own claim", () => {
    const a = mount();
    const b = mount();
    a.arm(file("a"));
    b.arm(file("b"));

    b.dispose();
    expect(activeDownload()?.name).toBe("a");

    a.dispose();
    expect(activeDownload()).toBeNull();
  });

  test("disposing the owner that is NOT on offer leaves the offer standing", () => {
    const a = mount();
    const b = mount();
    a.arm(file("a"));
    b.arm(file("b"));

    a.dispose();
    expect(activeDownload()?.name).toBe("b");
  });

  test("standing down clears only the caller, and can be re-armed", () => {
    const a = mount();
    const b = mount();
    a.arm(file("a"));
    b.arm(file("b"));

    b.arm(null);
    expect(activeDownload()?.name).toBe("a");

    b.arm(file("b2"));
    expect(activeDownload()?.name).toBe("b2");
  });

  test("standing down twice is harmless", () => {
    const a = mount();
    a.arm(file("a"));
    a.arm(null);
    a.arm(null);
    expect(activeDownload()).toBeNull();
  });
});
