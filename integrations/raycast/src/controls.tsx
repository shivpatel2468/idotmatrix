import { Action, ActionPanel, Color, Icon, List, showToast, Toast } from "@raycast/api";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type EngineState, flyPlay, frameUrl, type Meta, openStudio } from "./api";

const LEVELS = [5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100];

export default function Controls() {
  const [state, setState] = useState<EngineState>();
  const [error, setError] = useState<string>();
  const [frame, setFrame] = useState(frameUrl());
  const meta = useRef<Meta | undefined>(undefined);

  const refresh = useCallback(async () => {
    try {
      meta.current ??= await api.meta();
      setState(await api.state());
      setFrame(frameUrl());
      setError(undefined);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const t = setInterval(() => void refresh(), 2000);
    return () => clearInterval(t);
  }, [refresh]);

  const run = async (label: string, fn: () => Promise<unknown>) => {
    try {
      const msg = await fn();
      await showToast({ style: Toast.Style.Success, title: typeof msg === "string" ? msg : label });
      await refresh();
    } catch (e) {
      await showToast({ style: Toast.Style.Failure, title: (e as Error).message });
    }
  };

  const cur = state?.engine.current?.app;
  const curName = meta.current?.apps.find((a) => a.id === cur)?.name ?? cur ?? "nothing";
  const bri = state?.settings.brightness ?? 60;
  const power = state?.settings.power !== false;
  const playing = state?.engine.mode === "playlist" && state.engine.playlist.enabled;
  const live = (
    <List.Item.Detail
      markdown={`![Panel](${frame}&raycast-width=256&raycast-height=256)\n\n**Now showing:** ${curName}`}
    />
  );
  const setBri = (v: number) => {
    const b = Math.max(5, Math.min(100, v));
    return run(`Brightness ${b}%`, () => api.settings({ brightness: b }));
  };

  return (
    <List isLoading={!state && !error} isShowingDetail searchBarPlaceholder="Brightness, power, next…">
      {error && <List.EmptyView icon={Icon.Plug} title="DeskDot isn't reachable" description={error} />}
      {state && (
        <>
          <List.Section title="Now showing">
            <List.Item
              title={curName}
              subtitle={state.device.status}
              icon={{
                source: Icon.Monitor,
                tintColor: state.device.status === "connected" ? Color.Green : Color.Orange,
              }}
              detail={live}
              actions={
                <ActionPanel>
                  <Action title="Open Studio" icon={Icon.Globe} onAction={() => openStudio(cur ? `#app/${cur}` : "")} />
                </ActionPanel>
              }
            />
          </List.Section>
          <List.Section title="Playback">
            <List.Item
              title="Next"
              icon={Icon.Forward}
              detail={live}
              actions={
                <ActionPanel>
                  <Action title="Next" onAction={() => run("Next", () => api.playlist("next"))} />
                </ActionPanel>
              }
            />
            <List.Item
              title="Previous"
              icon={Icon.Rewind}
              detail={live}
              actions={
                <ActionPanel>
                  <Action title="Previous" onAction={() => run("Previous", () => api.playlist("prev"))} />
                </ActionPanel>
              }
            />
            <List.Item
              title={playing ? "Stop the Playlist" : "Play the Playlist"}
              icon={playing ? Icon.Stop : Icon.Play}
              detail={live}
              actions={
                <ActionPanel>
                  <Action
                    title={playing ? "Stop" : "Play"}
                    onAction={() =>
                      run(playing ? "Playlist stopped" : "Playlist playing", () =>
                        api.playlist(playing ? "stop" : "play"),
                      )
                    }
                  />
                </ActionPanel>
              }
            />
            <List.Item
              title="Let the Fly Play"
              icon={Icon.Bug}
              keywords={["fly", "brain", "ai"]}
              detail={live}
              actions={
                <ActionPanel>
                  <Action title="Let the Fly Play" onAction={() => run("The fly", () => flyPlay(meta.current, cur))} />
                </ActionPanel>
              }
            />
          </List.Section>
          <List.Section title="Panel">
            <List.Item
              title={power ? "Turn the Panel Off" : "Turn the Panel On"}
              icon={Icon.Power}
              detail={live}
              actions={
                <ActionPanel>
                  <Action
                    title={power ? "Turn off" : "Turn on"}
                    onAction={() => run(power ? "Panel off" : "Panel on", () => api.settings({ power: !power }))}
                  />
                </ActionPanel>
              }
            />
            <List.Item
              title="Brightness"
              subtitle={`${bri}%`}
              icon={Icon.Sun}
              keywords={["dim", "bright", "light"]}
              detail={live}
              actions={
                <ActionPanel>
                  <Action title="Brighter (+10%)" icon={Icon.ArrowUp} onAction={() => setBri(bri + 10)} />
                  <Action title="Dimmer (−10%)" icon={Icon.ArrowDown} onAction={() => setBri(bri - 10)} />
                  <ActionPanel.Submenu title="Set Brightness…" icon={Icon.Sun}>
                    {LEVELS.map((v) => (
                      <Action key={v} title={`${v}%`} onAction={() => setBri(v)} />
                    ))}
                  </ActionPanel.Submenu>
                  <Action
                    title="Display Settings in Studio"
                    icon={Icon.Gear}
                    onAction={() => openStudio("#settings/display")}
                  />
                </ActionPanel>
              }
            />
          </List.Section>
        </>
      )}
    </List>
  );
}
