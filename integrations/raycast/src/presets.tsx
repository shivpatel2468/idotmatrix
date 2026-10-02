import { Action, ActionPanel, Color, Icon, List, popToRoot, showToast, Toast } from "@raycast/api";
import { useEffect, useState } from "react";
import { api, type EngineState, type Meta, openStudio, type Preset, previewUrl } from "./api";

export default function Presets() {
  const [presets, setPresets] = useState<Preset[]>();
  const [meta, setMeta] = useState<Meta>();
  const [state, setState] = useState<EngineState>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    Promise.all([api.presets(), api.meta(), api.state()])
      .then(([p, m, s]) => {
        setPresets(p);
        setMeta(m);
        setState(s);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  const play = async (p: Preset, shuffle: boolean) => {
    try {
      await api.playPreset(p.id, shuffle);
      await showToast({ style: Toast.Style.Success, title: `Playing “${p.name}”${shuffle ? " (shuffled)" : ""}` });
      await popToRoot({ clearSearchBar: true });
    } catch (e) {
      await showToast({ style: Toast.Style.Failure, title: (e as Error).message });
    }
  };
  const name = (id: string) => meta?.apps.find((a) => a.id === id)?.name ?? id;
  const active = state?.engine.active_preset;
  const mine = (presets ?? []).filter((p) => !p.builtin);
  const builtin = (presets ?? []).filter((p) => p.builtin);

  const item = (p: Preset) => (
    <List.Item
      key={p.id}
      title={p.name}
      icon={Icon.List}
      keywords={p.items.map((i) => name(i.app))}
      accessories={[
        ...(p.id === active ? [{ tag: { value: "Playing", color: Color.Orange } }] : []),
        { text: `${p.items.length} apps` },
      ]}
      detail={
        <List.Item.Detail
          markdown={[
            p.items[0] ? `![](${previewUrl(p.items[0].app)}?raycast-width=160&raycast-height=160)` : "",
            `**${p.name}**`,
            p.items.map((i) => `- ${name(i.app)} · ${Math.round(i.duration)} s`).join("\n"),
          ].join("\n\n")}
        />
      }
      actions={
        <ActionPanel>
          <Action title="Play Preset" icon={Icon.Play} onAction={() => play(p, false)} />
          <Action title="Play Shuffled" icon={Icon.Shuffle} onAction={() => play(p, true)} />
          <Action title="Open Playlist in Studio" icon={Icon.Gear} onAction={() => openStudio("#settings/playlist")} />
        </ActionPanel>
      }
    />
  );

  return (
    <List isLoading={!presets && !error} isShowingDetail searchBarPlaceholder="Search presets…">
      {error && <List.EmptyView icon={Icon.Plug} title="DeskDot isn't reachable" description={error} />}
      {mine.length > 0 && <List.Section title="Yours">{mine.map(item)}</List.Section>}
      <List.Section title="Built in">{builtin.map(item)}</List.Section>
    </List>
  );
}
