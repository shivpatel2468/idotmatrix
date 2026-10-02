import { Action, ActionPanel, Form, Icon, popToRoot, showToast, Toast } from "@raycast/api";
import { api } from "./api";

type Values = { message: string; title: string; style: string; icon: string; color: string; duration: string };

const COLORS: [string, string][] = [
  ["Tangerine", "#ff7419"],
  ["Rose", "#ff3f78"],
  ["Gold", "#ffcc33"],
  ["Cyan", "#00dcff"],
  ["Green", "#00ff78"],
  ["White", "#ffffff"],
];
const ICONS = [
  "bell",
  "info",
  "ok",
  "warn",
  "error",
  "mail",
  "chat",
  "heart",
  "star",
  "music",
  "clock",
  "bolt",
  "claude",
];

export default function SendToPanel() {
  const submit = async (v: Values) => {
    if (!v.message.trim()) {
      await showToast({ style: Toast.Style.Failure, title: "Type a message" });
      return;
    }
    const seconds = Math.max(1, Math.min(120, Number(v.duration) || 8));
    try {
      if (v.style === "text") await api.text(v.message, v.color, Math.max(5, seconds));
      else
        await api.notify({
          title: v.title,
          message: v.message,
          color: v.color,
          icon: v.icon,
          duration: seconds,
          style: v.style,
        });
      await showToast({ style: Toast.Style.Success, title: "On the panel" });
      await popToRoot({ clearSearchBar: true });
    } catch (e) {
      await showToast({ style: Toast.Style.Failure, title: (e as Error).message });
    }
  };

  return (
    <Form
      actions={
        <ActionPanel>
          <Action.SubmitForm title="Send to Panel" icon={Icon.Upload} onSubmit={submit} />
        </ActionPanel>
      }
    >
      <Form.TextField id="message" title="Message" placeholder="Standup in 5" autoFocus />
      <Form.TextField id="title" title="Title" placeholder="Optional" />
      <Form.Dropdown id="style" title="Style" defaultValue="banner" storeValue>
        <Form.Dropdown.Item value="banner" title="Banner" />
        <Form.Dropdown.Item value="full" title="Full screen" />
        <Form.Dropdown.Item value="celebrate" title="Celebrate" />
        <Form.Dropdown.Item value="text" title="Scrolling text (then back)" />
      </Form.Dropdown>
      <Form.Dropdown id="icon" title="Icon" defaultValue="bell" storeValue>
        {ICONS.map((i) => (
          <Form.Dropdown.Item key={i} value={i} title={i} />
        ))}
      </Form.Dropdown>
      <Form.Dropdown id="color" title="Colour" defaultValue="#ff7419" storeValue>
        {COLORS.map(([n, c]) => (
          <Form.Dropdown.Item key={c} value={c} title={n} />
        ))}
      </Form.Dropdown>
      <Form.TextField id="duration" title="Seconds" defaultValue="8" />
    </Form>
  );
}
