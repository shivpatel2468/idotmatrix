import { Action, ActionPanel, Color, Icon, List, popToRoot, showToast, Toast } from "@raycast/api";
import { useEffect, useMemo, useState } from "react";
import {
  api,
  canFlyPilot,
  CATEGORY_LABEL,
  CATEGORY_ORDER,
  type EngineState,
  flyPlay,
  type Meta,
  openStudio,
  previewUrl,
} from "./api";

export default function SearchApps() {
  const [meta, setMeta] = useState<Meta>();
  const [state, setState] = useState<EngineState>();
  const [error, setError] = useState<string>();
  const [category, setCategory] = useState("all");

  useEffect(() => {
    Promise.all([api.meta(), api.state()])
      .then(([m, s]) => {
        setMeta(m);
        setState(s);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  const sections = useMemo(() => {
    const apps = (meta?.apps ?? []).filter(
      (a) => a.supported !== false && (category === "all" || a.category === category),
    );
    return CATEGORY_ORDER.map((c) => ({ c, apps: apps.filter((a) => a.category === c) })).filter((s) => s.apps.length);
  }, [meta, category]);

  const run = async (label: string, fn: () => Promise<unknown>) => {
    const t = await showToast({ style: Toast.Style.Animated, title: label });
    try {
      const msg = await fn();
      t.style = Toast.Style.Success;
      t.title = typeof msg === "string" ? msg : label;
      await popToRoot({ clearSearchBar: true });
    } catch (e) {
      t.style = Toast.Style.Failure;
      t.title = (e as Error).message;
    }
  };

  const current = state?.engine.current?.app;
  return (
    <List
      isLoading={!meta && !error}
      isShowingDetail
      searchBarPlaceholder="Search apps and games…"
      searchBarAccessory={
        <List.Dropdown tooltip="Category" onChange={setCategory} storeValue>
          <List.Dropdown.Item title="Everything" value="all" />
          {CATEGORY_ORDER.map((c) => (
            <List.Dropdown.Item key={c} title={CATEGORY_LABEL[c]} value={c} />
          ))}
        </List.Dropdown>
      }
    >
      {error && <List.EmptyView icon={Icon.Plug} title="DeskDot isn't reachable" description={error} />}
      {sections.map(({ c, apps }) => (
        <List.Section key={c} title={CATEGORY_LABEL[c] ?? c} subtitle={String(apps.length)}>
          {apps.map((a) => {
            const settings = Object.values(a.schema?.properties ?? {})
              .map((p) => p.title ?? "")
              .filter(Boolean);
            const game = a.category === "games";
            return (
              <List.Item
                key={a.id}
                title={a.name}
                keywords={[
                  a.id,
                  a.category,
                  CATEGORY_LABEL[a.category] ?? "",
                  ...settings,
                  ...a.description.split(/\s+/),
                ]}
                icon={game ? Icon.GameController : Icon.AppWindowGrid2x2}
                accessories={a.id === current ? [{ tag: { value: "On panel", color: Color.Orange } }] : []}
                detail={
                  <List.Item.Detail
                    markdown={`![${a.name}](${previewUrl(a.id)}?raycast-width=200&raycast-height=200)\n\n**${a.name}**\n\n${a.description}`}
                    metadata={
                      <List.Item.Detail.Metadata>
                        <List.Item.Detail.Metadata.Label
                          title="Category"
                          text={CATEGORY_LABEL[a.category] ?? a.category}
                        />
                        <List.Item.Detail.Metadata.Label title="Settings" text={String(settings.length)} />
                        {(a.max_players ?? 1) > 1 && (
                          <List.Item.Detail.Metadata.Label title="Players" text={`up to ${a.max_players}`} />
                        )}
                      </List.Item.Detail.Metadata>
                    }
                  />
                }
                actions={
                  <ActionPanel>
                    <Action
                      title={game ? "Play on Panel" : "Show on Panel"}
                      icon={Icon.Play}
                      onAction={() =>
                        run(`Showing ${a.name}…`, async () => {
                          await api.activate(a.id);
                          return `${a.name} is on the panel`;
                        })
                      }
                    />
                    <Action
                      title="Open Settings in Studio"
                      icon={Icon.Gear}
                      shortcut={{
                        macOS: { modifiers: ["cmd"], key: "return" },
                        Windows: { modifiers: ["ctrl"], key: "return" },
                      }}
                      onAction={() => openStudio(`#app/${a.id}`)}
                    />
                    {canFlyPilot(a) && (
                      <Action
                        title="Play with the Fly"
                        icon={Icon.Bug}
                        shortcut={{
                          macOS: { modifiers: ["cmd"], key: "f" },
                          Windows: { modifiers: ["ctrl"], key: "f" },
                        }}
                        onAction={() => run("Waking the fly…", () => flyPlay(meta, current, a.id))}
                      />
                    )}
                    <Action.CopyToClipboard title="Copy App ID" content={a.id} />
                  </ActionPanel>
                }
              />
            );
          })}
        </List.Section>
      ))}
    </List>
  );
}
