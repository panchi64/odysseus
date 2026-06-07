import { createSignal, type JSX } from "solid-js";
import { Button, Row } from "~/ui";

/** Message input. Enter sends; Shift+Enter inserts a newline. Disabled while a
 *  reply streams. */
export function Composer(props: {
  disabled?: boolean;
  onSend: (text: string) => void;
}): JSX.Element {
  const [text, setText] = createSignal("");

  const submit = () => {
    const value = text();
    if (!value.trim() || props.disabled) return;
    props.onSend(value);
    setText("");
  };

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div class="border-t border-line bg-surface p-3">
      <Row gap={2} align="end">
        <textarea
          value={text()}
          onInput={(e) => setText(e.currentTarget.value)}
          onKeyDown={onKeyDown}
          rows={1}
          placeholder="Message the agent…"
          disabled={props.disabled}
          class="min-h-8 flex-1 resize-none bg-bg border border-line px-2 py-1.5 rounded-ctl text-body font-mono text-bright placeholder:text-dim outline-none transition-colors focus:border-bright disabled:opacity-40"
        />
        <Button
          variant="primary"
          trailing="send"
          disabled={props.disabled || !text().trim()}
          onClick={submit}
        >
          SEND
        </Button>
      </Row>
    </div>
  );
}
