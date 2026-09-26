import { createSignal, type Accessor, type JSX } from "solid-js";

export interface FileDropApi {
  /** True while files are hovering the drop target. Drive a highlight off it. */
  isDragging: Accessor<boolean>;
  /** Spread onto the drop target element to wire drag-over/leave/drop. */
  dropHandlers: {
    onDragEnter: (e: DragEvent) => void;
    onDragOver: (e: DragEvent) => void;
    onDragLeave: (e: DragEvent) => void;
    onDrop: (e: DragEvent) => void;
  };
  /** Spread onto a focusable element (e.g. the textarea) to accept pasted
   *  images/files. A file-less paste (plain text) passes through untouched. */
  pasteHandlers: { onPaste: (e: ClipboardEvent) => void };
  /** Bind to a hidden `<input type="file">`'s ref so `openPicker` can click it. */
  bindInput: (el: HTMLInputElement) => void;
  /** Spread onto that hidden input to forward picked files to `onFiles`. */
  inputHandlers: { onChange: (e: Event) => void };
  /** Open the native file picker (e.g. from an attach button). */
  openPicker: () => void;
}

/**
 * The single drag/drop/pick/paste implementation behind the Composer's attach
 * affordance. Owns the drag-highlight state and funnels
 * dropped, picked, and pasted files through one `onFiles` callback — the consumer
 * decides what to do with them (upload, validate, etc.). No styling: it's a
 * behavior hook, so each surface renders its own chrome.
 *
 * `accepting` gates dropped and pasted files (the picker is the caller's to
 * disable). While it is false nothing is emitted and `isDragging` stays false, but
 * the drop is still *prevented* — an unhandled drop makes the browser navigate to
 * the file, which would take the whole app down with the draft in it.
 */
export function useFileDrop(
  onFiles: (files: File[]) => void,
  accepting: () => boolean = () => true,
): FileDropApi {
  const [isDragging, setIsDragging] = createSignal(false);
  let input: HTMLInputElement | undefined;
  // `dragenter`/`dragleave` fire for every child the pointer crosses, and a leave
  // from the target into its own child arrives *after* the child's enter. A plain
  // boolean therefore flickers off over the textarea and the chips; counting the
  // enters against the leaves only reaches zero when the pointer has really left.
  let depth = 0;

  const emit = (files: File[]) => {
    if (files.length) onFiles(files);
  };

  return {
    isDragging,
    dropHandlers: {
      onDragEnter: (e: DragEvent) => {
        e.preventDefault();
        depth++;
        setIsDragging(accepting());
      },
      onDragOver: (e: DragEvent) => {
        e.preventDefault();
        if (e.dataTransfer && !accepting()) e.dataTransfer.dropEffect = "none";
      },
      onDragLeave: () => {
        depth = Math.max(0, depth - 1);
        if (depth === 0) setIsDragging(false);
      },
      onDrop: (e: DragEvent) => {
        e.preventDefault();
        depth = 0;
        setIsDragging(false);
        if (accepting()) emit(Array.from(e.dataTransfer?.files ?? []));
      },
    },
    pasteHandlers: {
      onPaste: (e: ClipboardEvent) => {
        const files = Array.from(e.clipboardData?.files ?? []);
        // Plain-text paste, or files while not accepting: leave it to the field.
        if (!files.length || !accepting()) return;
        e.preventDefault();
        emit(files);
      },
    },
    bindInput: (el: HTMLInputElement) => {
      input = el;
    },
    inputHandlers: {
      onChange: (e: Event) => {
        const target = e.currentTarget as HTMLInputElement;
        emit(Array.from(target.files ?? []));
        target.value = ""; // allow re-picking the same file
      },
    },
    openPicker: () => input?.click(),
  };
}

/** Shared props for the hidden file input every drop surface renders. Spread the
 *  hook's `inputHandlers` and set `ref={api.bindInput}`. */
export const HIDDEN_FILE_INPUT: JSX.InputHTMLAttributes<HTMLInputElement> = {
  type: "file",
  multiple: true,
  class: "hidden",
};
