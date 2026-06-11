import type { JSX } from "solid-js";

/**
 * Geometric, stroke-based icons on a 16px grid (design system §5).
 * Each entry returns the inner SVG markup; the Icon primitive supplies the
 * <svg> wrapper, sizing, 1.5px stroke, currentColor, and round joins.
 * No filled, rounded, or skeuomorphic glyphs.
 */
export type IconName =
  | "cross"
  | "reticle"
  | "chevron-right"
  | "chevron-down"
  | "chevron-up"
  | "chevron-left"
  | "arrow-right"
  | "plus"
  | "minus"
  | "close"
  | "check"
  | "dot"
  | "search"
  | "menu"
  | "warning"
  | "info"
  | "lock"
  | "key"
  | "eye"
  | "edit"
  | "trash"
  | "refresh"
  | "download"
  | "upload"
  | "send"
  | "play"
  | "pause"
  | "stop"
  | "settings"
  | "user"
  | "users"
  | "mail"
  | "calendar"
  | "file"
  | "note"
  | "image"
  | "database"
  | "cpu"
  | "terminal"
  | "code"
  | "activity"
  | "link"
  | "plug"
  | "mic"
  | "clock"
  | "layers"
  | "grid"
  | "archive"
  | "library"
  | "pen"
  | "compare"
  | "research"
  | "copy"
  | "pin"
  | "sun"
  | "moon";

export const icons: Record<IconName, () => JSX.Element> = {
  cross: () => <path d="M8 3v10M3 8h10" />,
  reticle: () => (
    <>
      <circle cx="8" cy="8" r="5" />
      <path d="M8 1v3M8 12v3M1 8h3M12 8h3" />
    </>
  ),
  "chevron-right": () => <path d="M6 3l5 5-5 5" />,
  "chevron-down": () => <path d="M3 6l5 5 5-5" />,
  "chevron-up": () => <path d="M3 10l5-5 5 5" />,
  "chevron-left": () => <path d="M10 3L5 8l5 5" />,
  "arrow-right": () => <path d="M3 8h10M9 4l4 4-4 4" />,
  plus: () => <path d="M8 3v10M3 8h10" />,
  minus: () => <path d="M3 8h10" />,
  close: () => <path d="M4 4l8 8M12 4l-8 8" />,
  check: () => <path d="M3 8.5L6.5 12 13 4.5" />,
  dot: () => <circle cx="8" cy="8" r="2" />,
  search: () => (
    <>
      <circle cx="7" cy="7" r="4" />
      <path d="M10 10l3 3" />
    </>
  ),
  menu: () => <path d="M2 4h12M2 8h12M2 12h12" />,
  warning: () => (
    <>
      <path d="M8 2L15 14H1L8 2z" />
      <path d="M8 6v4M8 12v0.5" />
    </>
  ),
  info: () => (
    <>
      <circle cx="8" cy="8" r="6" />
      <path d="M8 7v4M8 5v0.5" />
    </>
  ),
  lock: () => (
    <>
      <rect x="3" y="7" width="10" height="7" />
      <path d="M5 7V5a3 3 0 0 1 6 0v2" />
    </>
  ),
  key: () => (
    <>
      <circle cx="5" cy="11" r="3" />
      <path d="M7 9l6-6M11 3l2 2M9 5l2 2" />
    </>
  ),
  eye: () => (
    <>
      <path d="M1 8s2.5-4 7-4 7 4 7 4-2.5 4-7 4-7-4-7-4z" />
      <circle cx="8" cy="8" r="2" />
    </>
  ),
  edit: () => <path d="M11 2l3 3L6 13H3v-3z" />,
  trash: () => (
    <>
      <path d="M2 4h12M5 4V2h6v2M4 4l1 10h6l1-10" />
    </>
  ),
  refresh: () => (
    <>
      <path d="M13 4v3h-3" />
      <path d="M13 7a5 5 0 1 0-1 5" />
    </>
  ),
  download: () => <path d="M8 2v8M5 7l3 3 3-3M3 13h10" />,
  upload: () => <path d="M8 11V3M5 6l3-3 3 3M3 13h10" />,
  send: () => <path d="M14 2L2 7l5 2 2 5z" />,
  play: () => <path d="M5 3l8 5-8 5z" />,
  pause: () => <path d="M5 3v10M11 3v10" />,
  stop: () => <rect x="4" y="4" width="8" height="8" />,
  settings: () => (
    <>
      <circle cx="8" cy="8" r="2.5" />
      <path d="M8 1v2M8 13v2M1 8h2M13 8h2M3 3l1.5 1.5M11.5 11.5L13 13M13 3l-1.5 1.5M4.5 11.5L3 13" />
    </>
  ),
  user: () => (
    <>
      <circle cx="8" cy="5" r="3" />
      <path d="M2 14a6 6 0 0 1 12 0" />
    </>
  ),
  users: () => (
    <>
      <circle cx="6" cy="5" r="2.5" />
      <path d="M1 14a5 5 0 0 1 10 0" />
      <path d="M11 4a2.5 2.5 0 0 1 0 5M14 14a4 4 0 0 0-3-3.8" />
    </>
  ),
  mail: () => (
    <>
      <rect x="2" y="4" width="12" height="9" />
      <path d="M2 5l6 4 6-4" />
    </>
  ),
  calendar: () => (
    <>
      <rect x="2" y="3" width="12" height="11" />
      <path d="M2 6h12M5 1v3M11 1v3" />
    </>
  ),
  file: () => (
    <>
      <path d="M4 2h5l3 3v9H4z" />
      <path d="M9 2v3h3" />
    </>
  ),
  note: () => (
    <>
      <rect x="3" y="2" width="10" height="12" />
      <path d="M5 5h6M5 8h6M5 11h4" />
    </>
  ),
  image: () => (
    <>
      <rect x="2" y="3" width="12" height="10" />
      <circle cx="6" cy="6.5" r="1.2" />
      <path d="M2 11l3.5-3 3 2.5L11 7l3 3" />
    </>
  ),
  database: () => (
    <>
      <ellipse cx="8" cy="4" rx="5" ry="2" />
      <path d="M3 4v8c0 1.1 2.2 2 5 2s5-0.9 5-2V4M3 8c0 1.1 2.2 2 5 2s5-0.9 5-2" />
    </>
  ),
  cpu: () => (
    <>
      <rect x="4" y="4" width="8" height="8" />
      <rect x="6.5" y="6.5" width="3" height="3" />
      <path d="M6 1v3M10 1v3M6 12v3M10 12v3M1 6h3M1 10h3M12 6h3M12 10h3" />
    </>
  ),
  terminal: () => (
    <>
      <rect x="2" y="3" width="12" height="10" />
      <path d="M4 6l2.5 2L4 10M8 10h4" />
    </>
  ),
  code: () => <path d="M6 4L2 8l4 4M10 4l4 4-4 4" />,
  activity: () => <path d="M1 8h3l2-5 4 10 2-5h3" />,
  link: () => (
    <>
      <path d="M6 10l4-4" />
      <path d="M9 4l1-1a2.8 2.8 0 0 1 4 4l-1 1M7 12l-1 1a2.8 2.8 0 0 1-4-4l1-1" />
    </>
  ),
  plug: () => (
    <>
      <path d="M6 2v4M10 2v4" />
      <path d="M4 6h8v2a4 4 0 0 1-8 0z" />
      <path d="M8 12v3" />
    </>
  ),
  mic: () => (
    <>
      <rect x="6" y="2" width="4" height="7" rx="2" />
      <path d="M4 8a4 4 0 0 0 8 0M8 12v2" />
    </>
  ),
  clock: () => (
    <>
      <circle cx="8" cy="8" r="6" />
      <path d="M8 4v4l3 2" />
    </>
  ),
  layers: () => <path d="M8 2L2 5l6 3 6-3zM2 9l6 3 6-3M2 12l6 3 6-3" />,
  grid: () => (
    <>
      <rect x="2" y="2" width="5" height="5" />
      <rect x="9" y="2" width="5" height="5" />
      <rect x="2" y="9" width="5" height="5" />
      <rect x="9" y="9" width="5" height="5" />
    </>
  ),
  archive: () => (
    <>
      <rect x="2" y="3" width="12" height="3" />
      <path d="M3 6v8h10V6M6 9h4" />
    </>
  ),
  library: () => (
    <>
      <path d="M3 2v12M6 2v12M9 3l3-1 2 11-3 1z" />
    </>
  ),
  pen: () => <path d="M2 14s1-3 3-5l5-5 2 2-5 5c-2 2-5 3-5 3z" />,
  compare: () => (
    <>
      <rect x="2" y="3" width="5" height="10" />
      <rect x="9" y="3" width="5" height="10" />
    </>
  ),
  research: () => (
    <>
      <circle cx="7" cy="7" r="4" />
      <path d="M10 10l4 4M7 5v4M5 7h4" />
    </>
  ),
  copy: () => (
    <>
      <rect x="5" y="5" width="9" height="9" />
      <path d="M11 5V2H2v9h3" />
    </>
  ),
  sun: () => (
    <>
      <circle cx="8" cy="8" r="3" />
      <path d="M8 1v2M8 13v2M1 8h2M13 8h2M3 3l1.5 1.5M11.5 11.5L13 13M13 3l-1.5 1.5M4.5 11.5L3 13" />
    </>
  ),
  moon: () => <path d="M13 9.5A5.5 5.5 0 1 1 6.5 3 4.5 4.5 0 0 0 13 9.5z" />,
  pin: () => (
    <>
      <path d="M6 2h4l-1 5 3 3H4l3-3z" />
      <path d="M8 10v4" />
    </>
  ),
};
