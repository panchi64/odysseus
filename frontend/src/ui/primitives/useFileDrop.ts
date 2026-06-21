import { createSignal, type Accessor, type JSX } from "solid-js";

export interface FileDropApi {
  /** True while files are hovering the drop target. Drive a highlight off it. */
  isDragging: Accessor<boolean>;
  /** Spread onto the drop target element to wire drag-over/leave/drop. */
  dropHandlers: {
    onDragOver: (e: DragEvent) => void;
    onDragLeave: (e: DragEvent) => void;
    onDrop: (e: DragEvent) => void;
  };
  /** Bind to a hidden `<input type="file">`'s ref so `openPicker` can click it. */
  bindInput: (el: HTMLInputElement) => void;
  /** Spread onto that hidden input to forward picked files to `onFiles`. */
  inputHandlers: { onChange: (e: Event) => void };
  /** Open the native file picker (e.g. from an attach button). */
  openPicker: () => void;
}

/**
 * The single drag/drop/pick implementation shared by the uploads DropZone and
 * the Composer's attach affordance. Owns the drag-highlight state and funnels
 * both dropped and picked files through one `onFiles` callback — the consumer
 * decides what to do with them (upload, validate, etc.). No styling: it's a
 * behavior hook, so each surface renders its own chrome.
 */
export function useFileDrop(onFiles: (files: File[]) => void): FileDropApi {
  const [isDragging, setIsDragging] = createSignal(false);
  let input: HTMLInputElement | undefined;

  const emit = (files: File[]) => {
    if (files.length) onFiles(files);
  };

  return {
    isDragging,
    dropHandlers: {
      onDragOver: (e: DragEvent) => {
        e.preventDefault();
        setIsDragging(true);
      },
      onDragLeave: () => setIsDragging(false),
      onDrop: (e: DragEvent) => {
        e.preventDefault();
        setIsDragging(false);
        emit(Array.from(e.dataTransfer?.files ?? []));
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
