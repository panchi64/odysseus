/**
 * Public surface of the design system. Everything outside `src/ui` imports
 * components and types from here (`~/ui`), never from deep paths.
 *
 * Rules (see src/ui/CLAUDE.md):
 *  - tokens.css is the single source of truth for colors/spacing/type.
 *  - Cosmetic differences are variant props, never forked components.
 *  - No spinners — use LoadingText / EmptyState.
 */

// utils
export { cx, type ClassValue } from "./cx";
export { copyToClipboard } from "./clipboard";

// theme
export {
  preference,
  setTheme,
  toggleTheme,
  applyTheme,
  resolveTheme,
  systemTheme,
  syncSystemTheme,
  DEFAULT_THEME,
  DEFAULT_PREFERENCE,
  THEME_STORAGE_KEY,
  THEME_CYCLE,
  type ThemeMode,
  type ThemePreference,
} from "./theme/theme-store";
export { useTheme } from "./theme/useTheme";
export { ThemeProvider } from "./theme/ThemeProvider";

// primitives
export { Box } from "./primitives/Box";
export {
  Text,
  type TextProps,
  type TextVariant,
  type TextTone,
} from "./primitives/Text";
export { Stack, type StackProps, type GapStep } from "./primitives/Stack";
export { Row, type RowProps } from "./primitives/Row";
export { Icon, type IconProps } from "./primitives/Icon";
export { type IconName } from "./icons/registry";

// spec components
export { Panel, type PanelProps, type PanelState } from "./components/Panel";
export { Field, type FieldProps } from "./components/Field";
export { Readout, type ReadoutProps } from "./components/Readout";
export {
  StatusFlag,
  type StatusFlagProps,
  type Status,
} from "./components/StatusFlag";
export {
  InstrumentBand,
  type InstrumentBandProps,
  type BandCell,
} from "./components/InstrumentBand";
export { Tile, type TileProps } from "./components/Tile";
export { Chip, type ChipProps } from "./components/Chip";
export { ListRow, type ListRowProps } from "./components/ListRow";
export { ListToolbar, type ListToolbarProps } from "./components/ListToolbar";
export {
  RegistrationFrame,
  type RegistrationFrameProps,
} from "./components/RegistrationFrame";

// controls
export {
  Button,
  type ButtonProps,
  type ButtonVariant,
  type ButtonSize,
} from "./components/Button";
export { Input, type InputProps } from "./components/Input";
export { Textarea, type TextareaProps } from "./components/Textarea";
export { Composer, type ComposerProps } from "./components/Composer";
export { Markdown, type MarkdownProps } from "./components/Markdown";
export {
  Select,
  type SelectProps,
  type SelectOption,
} from "./components/Select";
export { Checkbox, type CheckboxProps } from "./components/Checkbox";
export { Toggle, type ToggleProps } from "./components/Toggle";
export { Tabs, type TabsProps, type TabItem } from "./components/Tabs";
export { Modal, type ModalProps } from "./components/Modal";
export { Drawer, type DrawerProps } from "./components/Drawer";
export { Tooltip, type TooltipProps } from "./components/Tooltip";
export { InfoHint, type InfoHintProps } from "./components/InfoHint";
export {
  ExpandableText,
  type ExpandableTextProps,
} from "./components/ExpandableText";
export { Menu, type MenuProps, type MenuItem } from "./components/Menu";
export { ThemeToggle } from "./components/ThemeToggle";

// state / utility
export { LoadingText, type LoadingTextProps } from "./components/LoadingText";
export { EmptyState, type EmptyStateProps } from "./components/EmptyState";
export { ErrorState, type ErrorStateProps } from "./components/ErrorState";
export { Resource, type ResourceProps } from "./components/Resource";
export { EditorShell, type EditorShellProps } from "./components/EditorShell";
export {
  toast,
  Toaster,
  type ToastTone,
  type ToastAction,
  type ToastOptions,
} from "./components/Toast";
export {
  confirm,
  ConfirmHost,
  type ConfirmTone,
  type ConfirmOptions,
} from "./components/Confirm";
export {
  ForbiddenView,
  type ForbiddenViewProps,
} from "./components/ForbiddenView";
export { ProgressBar, type ProgressBarProps } from "./components/ProgressBar";
export { Divider, type DividerProps } from "./components/Divider";
export { Marquee, type MarqueeProps } from "./components/Marquee";
export { PageHeader, type PageHeaderProps } from "./components/PageHeader";
export { NotConnectedOverlay } from "./components/NotConnectedOverlay";
