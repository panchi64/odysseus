/**
 * The settings index's derivations, and the palette's two-kind result list.
 *
 * Everything under test is pure and takes its entries as an argument, exactly
 * as `nav.test.ts` injects `areas` — so a rule fails here when the rule changes,
 * not when a setting is added to the real registry.
 *
 * The fixture is ordered to **fight** every rule it exercises: declaration order
 * disagrees with ranking order, with grouping order, and with kind order, so a
 * dropped rule can't be rescued by the array happening to already be right.
 */
import { describe, expect, test } from "bun:test";
import {
  PAGES_SECTION,
  flattenNav,
  paletteDirectory,
  paletteSections,
  searchNav,
  searchPalette,
} from "./index";
import {
  formatSettingValue,
  nextChoiceValue,
  parseSettingNumber,
  searchSettings,
} from "./settings-search";
import type {
  ChoiceSetting,
  NavArea,
  NumberSetting,
  SettingEntry,
  ToggleSetting,
} from "./types";

const toggle = (
  id: string,
  label: string,
  group: string,
  keywords: string[] = [],
  value = false,
): ToggleSetting => ({
  id,
  label,
  keywords,
  group,
  kind: "toggle",
  read: () => value,
  write: () => {},
});

/** Matches "offline" on its LABEL *and* on a keyword, deliberately: it is the
 *  only entry that can prove the buckets are exclusive, since an entry matching
 *  one field alone comes back once either way. */
const OFFLINE_TOGGLE = toggle("net.offline", "Offline mode", "NETWORK", [
  "offline",
  "network",
]);

/** Ordered so each rule is exercised by data that would break if the rule were
 *  dropped:
 *   - "offline" is the LABEL of the last entry, a KEYWORD on the second, and the
 *     GROUP of the third and fourth — and they are declared worst-rank-first, so
 *     declaration order gives exactly the wrong answer.
 *   - the two CHAT entries straddle a NETWORK one, so first-appearance grouping
 *     and a naive "group when adjacent" fold disagree. */
const FIXTURE: SettingEntry[] = [
  // GROUP-only match, declared first.
  toggle("net.autodetect", "Detect connectivity", "OFFLINE"),
  // KEYWORD match, declared second.
  toggle("chat.fold", "Fold older turns", "CHAT", ["offline", "compaction"]),
  // Another group-only match, and the entry that separates the two CHAT rows.
  toggle("net.suspend", "Suspend web containers", "OFFLINE"),
  // Second CHAT entry, non-adjacent to the first.
  toggle("chat.limit", "Step limit", "CHAT"),
  // LABEL match, declared LAST — it must come back FIRST.
  OFFLINE_TOGGLE,
];

const NUMBER: NumberSetting = {
  id: "chat.threshold",
  label: "Auto-compact trigger",
  keywords: [],
  group: "CHAT",
  kind: "number",
  unit: "%",
  min: 1,
  max: 100,
  read: () => 95,
  write: () => {},
};

const CHOICE: ChoiceSetting = {
  id: "ui.theme",
  label: "Theme",
  keywords: [],
  group: "APPEARANCE",
  kind: "choice",
  options: [
    { value: "phosphor", label: "PHOSPHOR" },
    { value: "paper", label: "PAPER" },
    { value: "system", label: "SYSTEM" },
  ],
  read: () => "paper",
  write: () => {},
};

/** Two pages whose labels both contain "offline", so the palette test proves
 *  pages and settings are both searched — and that pages stay first. */
const AREAS_FIXTURE: NavArea[] = [
  {
    id: "system",
    label: "SYSTEM",
    icon: "file",
    description: "system area",
    items: [
      {
        label: "Offline Mode",
        href: "/settings/offline",
        icon: "file",
        description: "What stays available with no network",
      },
      {
        label: "Appearance",
        href: "/settings/appearance",
        icon: "file",
        description: "Theme and how the workspace looks",
      },
    ],
  },
];

describe("searchSettings", () => {
  test("an empty query returns nothing", () => {
    expect(searchSettings("", FIXTURE)).toEqual([]);
    expect(searchSettings("   ", FIXTURE)).toEqual([]);
  });

  test("label beats keyword beats group", () => {
    // Declaration order is group, keyword, group, —, label. Anything that keeps
    // source order, or ranks only two of the three fields, gets this wrong.
    expect(searchSettings("offline", FIXTURE).map((e) => e.id)).toEqual([
      "net.offline",
      "chat.fold",
      "net.autodetect",
      "net.suspend",
    ]);
  });

  test("an entry is counted once, by its strongest field", () => {
    // "Offline mode" is in group NETWORK, but were the buckets not exclusive a
    // keyword/group pass could re-add a label hit further down the list.
    const hits = searchSettings("offline", FIXTURE).filter(
      (e) => e.id === "net.offline",
    );
    expect(hits).toHaveLength(1);
  });

  test("a keyword makes a setting findable by a word its label never uses", () => {
    // "Fold older turns" says nothing about compaction; the keyword is the only
    // path to it.
    expect(searchSettings("compaction", FIXTURE).map((e) => e.id)).toEqual([
      "chat.fold",
    ]);
  });

  test("is case-insensitive on every field", () => {
    expect(searchSettings("OFFLINE", FIXTURE).map((e) => e.id)).toEqual(
      searchSettings("offline", FIXTURE).map((e) => e.id),
    );
  });
});

describe("formatSettingValue", () => {
  test("an unloaded value reads as a dash, not as a plausible default", () => {
    // The seam hasn't answered yet. "OFF" here would state a value the operator
    // is about to act on, and be wrong half the time.
    expect(formatSettingValue(OFFLINE_TOGGLE, undefined)).toBe("—");
    expect(formatSettingValue(NUMBER, undefined)).toBe("—");
    expect(formatSettingValue(CHOICE, undefined)).toBe("—");
  });

  test("a toggle reads ON / OFF", () => {
    expect(formatSettingValue(OFFLINE_TOGGLE, true)).toBe("ON");
    expect(formatSettingValue(OFFLINE_TOGGLE, false)).toBe("OFF");
  });

  test("a number carries its unit, and zero is a value, not an absence", () => {
    expect(formatSettingValue(NUMBER, 95)).toBe("95%");
    // 0 is falsy — a truthiness check where the undefined check belongs would
    // render this as a dash.
    expect(formatSettingValue(NUMBER, 0)).toBe("0%");
  });

  test("a choice reads its option's label, not its wire value", () => {
    expect(formatSettingValue(CHOICE, "paper")).toBe("PAPER");
  });

  test("a choice value with no matching option still renders as itself", () => {
    // The seam is the authority on what it holds; showing nothing would show the
    // operator the wrong state.
    expect(formatSettingValue(CHOICE, "sepia")).toBe("sepia");
  });
});

describe("nextChoiceValue", () => {
  test("cycles forward and wraps at the end", () => {
    expect(nextChoiceValue(CHOICE.options, "phosphor")).toBe("paper");
    expect(nextChoiceValue(CHOICE.options, "paper")).toBe("system");
    expect(nextChoiceValue(CHOICE.options, "system")).toBe("phosphor");
  });

  test("an unknown current value starts the cycle rather than dead-ending", () => {
    expect(nextChoiceValue(CHOICE.options, "sepia")).toBe("phosphor");
    expect(nextChoiceValue(CHOICE.options, undefined)).toBe("phosphor");
  });

  test("no options means nothing to cycle to", () => {
    expect(nextChoiceValue([], "phosphor")).toBeUndefined();
  });
});

describe("parseSettingNumber", () => {
  test("accepts a whole number inside the bounds", () => {
    expect(parseSettingNumber(NUMBER, "42")).toBe(42);
    expect(parseSettingNumber(NUMBER, "  42  ")).toBe(42);
    // The bounds are inclusive.
    expect(parseSettingNumber(NUMBER, "1")).toBe(1);
    expect(parseSettingNumber(NUMBER, "100")).toBe(100);
  });

  test("a blank field is rejected rather than read as zero", () => {
    // Number("") is 0, which would silently save a 0. Asserted against a setting
    // with NO lower bound on purpose: against `NUMBER` the `min: 1` check would
    // reject the 0 anyway and the blank guard could be deleted unnoticed.
    const unbounded: NumberSetting = {
      ...NUMBER,
      min: undefined,
      max: undefined,
    };
    expect(parseSettingNumber(unbounded, "")).toBeNull();
    expect(parseSettingNumber(unbounded, "   ")).toBeNull();
    // And it is genuinely the blankness, not the value — 0 typed out is fine
    // where nothing bounds it.
    expect(parseSettingNumber(unbounded, "0")).toBe(0);
  });

  test("rejects non-integers and non-numbers", () => {
    expect(parseSettingNumber(NUMBER, "42.5")).toBeNull();
    expect(parseSettingNumber(NUMBER, "abc")).toBeNull();
  });

  test("rejects values outside the bounds", () => {
    expect(parseSettingNumber(NUMBER, "0")).toBeNull();
    expect(parseSettingNumber(NUMBER, "101")).toBeNull();
  });

  test("an absent bound doesn't bound", () => {
    const openEnded: NumberSetting = { ...NUMBER, min: 1, max: undefined };
    expect(parseSettingNumber(openEnded, "9999")).toBe(9999);
  });
});

describe("searchPalette", () => {
  test("searches pages and settings, pages first", () => {
    // Both a page and a setting are called "Offline …". The page must lead, so
    // Enter keeps doing what it always did for the row at the top.
    const hits = searchPalette("offline", {
      areas: AREAS_FIXTURE,
      settings: FIXTURE,
    });
    expect(hits[0]?.kind).toBe("nav");
    // Derived, not counted by hand: `flattenNav` also folds in the real PINS, so
    // a literal here would be a claim about the rail rather than about the
    // palette's composition rule.
    expect(hits.filter((h) => h.kind === "nav")).toHaveLength(
      searchNav("offline", AREAS_FIXTURE).length,
    );
    // Every nav hit precedes every setting hit.
    const firstSetting = hits.findIndex((h) => h.kind === "setting");
    expect(hits.slice(0, firstSetting).every((h) => h.kind === "nav")).toBe(
      true,
    );
    expect(hits.slice(firstSetting).every((h) => h.kind === "setting")).toBe(
      true,
    );
  });

  test("settings keep their own ranking inside the palette's result list", () => {
    const settings = searchPalette("offline", {
      areas: AREAS_FIXTURE,
      settings: FIXTURE,
    })
      .filter((h) => h.kind === "setting")
      .map((h) => (h.kind === "setting" ? h.setting.id : ""));
    expect(settings[0]).toBe("net.offline");
  });

  test("with no settings supplied it behaves exactly as the nav-only palette did", () => {
    const hits = searchPalette("offline", { areas: AREAS_FIXTURE });
    expect(hits.every((h) => h.kind === "nav")).toBe(true);
  });
});

describe("paletteDirectory", () => {
  test("lists every page and every setting when nothing is typed", () => {
    const hits = paletteDirectory({
      areas: AREAS_FIXTURE,
      settings: FIXTURE,
    });
    expect(hits.filter((h) => h.kind === "nav")).toHaveLength(
      flattenNav(AREAS_FIXTURE).length,
    );
    expect(hits.filter((h) => h.kind === "setting")).toHaveLength(
      FIXTURE.length,
    );
  });
});

describe("paletteSections", () => {
  const sections = () =>
    paletteSections(
      paletteDirectory({ areas: AREAS_FIXTURE, settings: FIXTURE }),
    );
  /** Where the settings begin in the flat list — the pages come first, and how
   *  many there are is `flattenNav`'s business (areas plus the real pins). */
  const settingsStart = flattenNav(AREAS_FIXTURE).length;
  const indexOf = (id: string): number =>
    settingsStart + FIXTURE.findIndex((e) => e.id === id);

  test("pages file under one heading and settings under their own groups", () => {
    // The whole point of the split: a settings row can never read as a page.
    expect(sections().map((s) => s.label)).toEqual([
      PAGES_SECTION,
      "OFFLINE",
      "CHAT",
      "NETWORK",
    ]);
  });

  test("a group collects its non-adjacent entries", () => {
    // The two CHAT entries are declared with a NETWORK-group entry between them;
    // a fold that only groups neighbours would emit CHAT twice.
    const chat = sections().find((s) => s.label === "CHAT");
    expect(chat?.rows.map((r) => r.index)).toEqual([
      indexOf("chat.fold"),
      indexOf("chat.limit"),
    ]);
  });

  test("each row carries the flat index the cursor navigates by", () => {
    // Sections reorder nothing, but they do interrupt the run — so the index
    // must come from the flat list, not from a per-section counter.
    const total = settingsStart + FIXTURE.length;
    const expected = Array.from({ length: total }, (_, i) => i);
    const all = sections().flatMap((s) => s.rows.map((r) => r.index));
    expect(all.slice().sort((a, b) => a - b)).toEqual(expected);
    // Grouping moved rows relative to the flat order — that is exactly why the
    // index has to ride along.
    expect(all).not.toEqual(expected);
  });

  test("an empty result list has no sections", () => {
    expect(paletteSections([])).toEqual([]);
  });
});
