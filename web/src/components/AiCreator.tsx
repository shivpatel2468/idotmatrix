import { useEffect, useRef, useState } from "react";
import {
  Brush,
  Check,
  Download,
  Key,
  Layers,
  Pause,
  Play,
  SkipBack,
  SkipForward,
  Sparkles,
  X,
  Zap,
} from "lucide-react";
import { api } from "../lib/api";
import { toast, useStore } from "../lib/store";

const PRESET_PROMPTS = [
  { label: "🔥 Campfire Glow", prompt: "A flickering pixel art campfire with rising embers and warm yellow-orange flame animation" },
  { label: "🚀 Retro Rocket", prompt: "A retro 8-bit rocket spaceship ascending through dark space with thruster fire pulsing" },
  { label: "⚡ Neon Heart", prompt: "A glowing magenta and cyan neon heart with a smooth pulsing heartbeat rhythm" },
  { label: "🌧️ Cyber Thunderstorm", prompt: "A dark storm cloud with striking electric blue lightning bolts and neon falling raindrops" },
  { label: "🐱 Pixel Cat Tail", prompt: "A cute sitting pixel cat with glowing green eyes gently wagging its tail back and forth" },
  { label: "👾 Arcade Ghost", prompt: "A retro arcade 8-bit floating ghost wavering left and right with blinking eyes" },
  { label: "☕ Steaming Mug", prompt: "A warm mug of coffee with rising curly wisps of steam on a calm desk" },
  { label: "🪐 Orbiting Planet", prompt: "A ringed Saturn-like planet with a tiny glowing moon orbiting smoothly around it" },
];

export function AiCreator() {
  const open = useStore((s) => s.aiOpen);
  const set = useStore((s) => s.set);

  const [apiKey, setApiKey] = useState("");
  const [maskedKey, setMaskedKey] = useState("");
  const [hasConfig, setHasConfig] = useState(false);
  const [showKeyInput, setShowKeyInput] = useState(false);
  const [model, setModel] = useState("gemini-2.5-flash");
  const [prompt, setPrompt] = useState("");
  const [numFrames, setNumFrames] = useState(8);
  const [fps, setFps] = useState(8);

  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState<{
    title: string;
    media_id: string;
    fps: number;
    frame_count: number;
    frames: { rows: string[]; duration_ms: number }[];
    palette: Record<string, string>;
    gif_url: string;
  } | null>(null);

  // Playback state
  const [currentFrame, setCurrentFrame] = useState(0);
  const [playing, setPlaying] = useState(true);
  const playTimer = useRef<number | null>(null);

  // Load server AI config on mount
  useEffect(() => {
    if (!open) return;
    api.aiConfig().then((cfg) => {
      setHasConfig(cfg.configured);
      setMaskedKey(cfg.masked_key || "");
      if (cfg.model) setModel(cfg.model);
      if (!cfg.configured) setShowKeyInput(true);
    }).catch(() => {});
  }, [open]);

  // Frame animation loop
  useEffect(() => {
    if (!result || !result.frames.length || !playing) {
      if (playTimer.current) window.clearInterval(playTimer.current);
      return;
    }
    const ms = Math.max(40, result.frames[currentFrame]?.duration_ms || Math.round(1000 / fps));
    playTimer.current = window.setTimeout(() => {
      setCurrentFrame((prev) => (prev + 1) % result.frames.length);
    }, ms);
    return () => {
      if (playTimer.current) window.clearTimeout(playTimer.current);
    };
  }, [result, playing, currentFrame, fps]);

  if (!open) return null;

  const saveKey = async () => {
    if (!apiKey.trim()) return;
    try {
      const res = await api.aiSaveConfig({ api_key: apiKey.trim(), model });
      setHasConfig(res.configured);
      setMaskedKey(res.masked_key);
      setShowKeyInput(false);
      setApiKey("");
      toast("Gemini API key saved securely!", "ok");
    } catch (e: any) {
      toast(e.message || "Failed to save key", "error");
    }
  };

  const generate = async (action: "preview" | "canvas" | "clip" = "preview") => {
    if (!prompt.trim()) {
      toast("Please enter a prompt to generate.", "error");
      return;
    }
    setGenerating(true);
    try {
      const res = await api.aiCreate({
        prompt: prompt.trim(),
        api_key: apiKey.trim() || undefined,
        model,
        fps,
        num_frames: numFrames,
        action,
      });
      setResult(res);
      setCurrentFrame(0);
      setPlaying(true);
      if (action === "clip") {
        toast(`"${res.title}" baked & uploaded to panel!`, "ok");
      } else if (action === "canvas") {
        toast(`"${res.title}" loaded onto canvas!`, "ok");
      } else {
        toast(`Generated "${res.title}" with ${res.frame_count} frames!`, "ok");
      }
    } catch (e: any) {
      toast(e.message || "Generation failed", "error");
    } finally {
      setGenerating(false);
    }
  };

  const loadFrameToCanvas = async (frameIdx: number) => {
    if (!result) return;
    const f = result.frames[frameIdx];
    if (!f) return;
    try {
      await api.pixels({ rows: f.rows, palette: result.palette, clear: true });
      toast(`Frame ${frameIdx + 1} loaded into Canvas`, "ok");
    } catch (e: any) {
      toast("Failed to load frame into Canvas", "error");
    }
  };

  const pushToPanelLoop = async () => {
    if (!result) return;
    try {
      await api.activate("gallery", { media: result.media_id });
      toast("Native GIF loop sent to panel!", "ok");
    } catch (e: any) {
      toast("Failed to activate on panel", "error");
    }
  };

  // Render 32x32 LED preview for current frame
  const renderLedGrid = () => {
    if (!result || !result.frames.length) return null;
    const frame = result.frames[currentFrame] || result.frames[0];
    const pal = result.palette;

    return (
      <div className="relative aspect-square w-full max-w-[280px] rounded-[14px] bg-[#050508] p-3 shadow-[inset_0_2px_8px_rgba(0,0,0,0.8),0_0_20px_rgba(0,0,0,0.6)] border border-[#202028]">
        <div className="grid h-full w-full grid-cols-32 grid-rows-32 gap-[1px]">
          {frame.rows.map((row, y) =>
            row.split("").map((ch, x) => {
              const hex = pal[ch] || "#000000";
              const isLit = hex !== "#000000";
              return (
                <div
                  key={`${y}-${x}`}
                  className="rounded-[0.5px] transition-colors duration-75"
                  style={{
                    backgroundColor: hex,
                    boxShadow: isLit ? `0 0 3px ${hex}` : "none",
                  }}
                />
              );
            })
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-black/70 backdrop-blur-[4px] animate-fade">
      <div className="surface flex max-h-[92vh] w-full max-w-4xl flex-col overflow-hidden rounded-[18px] border border-line-2 shadow-2xl animate-rise">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-line bg-chassis-2 px-5 py-3.5">
          <div className="flex items-center gap-3">
            <span className="grid h-9 w-9 place-items-center rounded-[10px] bg-gradient-to-tr from-amber-500/20 via-ember/20 to-purple-500/20 border border-ember/30 text-ember">
              <Sparkles size={18} />
            </span>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="font-display text-[17px] font-[680] leading-none tracking-[-0.02em]">
                  Gemini Pixel Studio
                </h2>
                <span className="engrave !text-[8px] bg-chassis-0 border border-line px-1.5 py-0.5 rounded text-ember">
                  32×32 Native
                </span>
              </div>
              <p className="mt-1 text-[11.5px] text-ink-3">
                Generative AI pixel art &amp; multi-frame native loops for iDotMatrix
              </p>
            </div>
          </div>
          <button
            onClick={() => set({ aiOpen: false })}
            className="rounded-lg p-1.5 text-ink-3 hover:bg-chassis-3 hover:text-ink-1 transition"
          >
            <X size={16} />
          </button>
        </div>

        {/* API Key Bar */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line/60 bg-chassis-1 px-5 py-2 text-[12px]">
          <div className="flex items-center gap-2 text-ink-2">
            <Key size={13} className="text-amber-400" />
            <span>Gemini API:</span>
            {hasConfig && !showKeyInput ? (
              <span className="flex items-center gap-1.5 text-ok font-mono text-[11px] bg-chassis-2 px-2 py-0.5 rounded border border-line">
                <Check size={11} /> {maskedKey || "Configured"}
              </span>
            ) : (
              <span className="text-warn text-[11.5px]">Key needed for generation</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {showKeyInput ? (
              <div className="flex items-center gap-1.5">
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="Paste AI Studio Key (AIza...)"
                  className="rounded-[6px] border border-line-2 bg-chassis-0 px-2 py-1 text-[11px] font-mono w-52 text-ink-1 focus:border-ember outline-none"
                />
                <button onClick={saveKey} className="key key-sm key-ember text-[11px] py-1 px-2.5">
                  Save
                </button>
                <button
                  onClick={() => setShowKeyInput(false)}
                  className="text-ink-3 hover:text-ink-1 px-1 text-[11px]"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <button
                onClick={() => setShowKeyInput(true)}
                className="text-[11px] text-ink-3 hover:text-ink-1 underline underline-offset-2"
              >
                {hasConfig ? "Change Key" : "Enter API Key"}
              </button>
            )}
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className="rounded-[6px] border border-line bg-chassis-0 px-2 py-1 text-[11px] text-ink-2 outline-none"
            >
              <option value="gemini-2.5-flash">Gemini 2.5 Flash (Fast)</option>
              <option value="gemini-1.5-flash">Gemini 1.5 Flash</option>
              <option value="gemini-2.5-pro">Gemini 2.5 Pro (Deep)</option>
            </select>
          </div>
        </div>

        {/* Body content */}
        <div className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto md:grid-cols-12 divide-y md:divide-y-0 md:divide-x divide-line">
          {/* Left panel: Prompt & Controls */}
          <div className="flex flex-col gap-4 p-5 md:col-span-7">
            {/* Quick preset chips */}
            <div>
              <div className="engrave !text-[9px] mb-2 text-ink-3">Inspiration Presets</div>
              <div className="flex flex-wrap gap-1.5">
                {PRESET_PROMPTS.map((p) => (
                  <button
                    key={p.label}
                    onClick={() => setPrompt(p.prompt)}
                    className="rounded-[6px] border border-line bg-chassis-2 px-2.5 py-1 text-[11.5px] text-ink-2 transition hover:border-ember/50 hover:bg-chassis-3 hover:text-ink-1"
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Prompt Textarea */}
            <div className="flex-1 min-h-[100px]">
              <label className="engrave !text-[9px] block mb-1.5 text-ink-3">
                Prompt (Hardware-optimized prompt template automatically injected)
              </label>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="Describe what to create: e.g. Cyberpunk neon samurai mask with blinking eyes, retro arcade explosion, or floating pixel spaceship..."
                rows={4}
                className="w-full resize-none rounded-[10px] border border-line-2 bg-chassis-0 p-3 text-[13px] text-ink-1 placeholder:text-ink-4 focus:border-ember outline-none leading-relaxed"
              />
            </div>

            {/* Sliders: Frame count & FPS */}
            <div className="grid grid-cols-2 gap-4 rounded-[10px] border border-line bg-chassis-1 p-3">
              <div>
                <div className="flex justify-between text-[11.5px] text-ink-2 mb-1">
                  <span>Animation Frames:</span>
                  <span className="font-mono text-ember">{numFrames} frames</span>
                </div>
                <input
                  type="range"
                  min={1}
                  max={16}
                  value={numFrames}
                  onChange={(e) => setNumFrames(+e.target.value)}
                  className="w-full accent-ember"
                />
                <div className="flex justify-between text-[9px] text-ink-4 mt-0.5">
                  <span>1 (Still)</span>
                  <span>8 (Standard)</span>
                  <span>16 (Max)</span>
                </div>
              </div>

              <div>
                <div className="flex justify-between text-[11.5px] text-ink-2 mb-1">
                  <span>Playback Speed:</span>
                  <span className="font-mono text-ember">{fps} FPS</span>
                </div>
                <input
                  type="range"
                  min={4}
                  max={16}
                  value={fps}
                  onChange={(e) => setFps(+e.target.value)}
                  className="w-full accent-ember"
                />
                <div className="flex justify-between text-[9px] text-ink-4 mt-0.5">
                  <span>4 fps</span>
                  <span>8 fps (Ideal)</span>
                  <span>16 fps</span>
                </div>
              </div>
            </div>

            {/* Main Generation CTA */}
            <div className="flex gap-2.5 pt-1">
              <button
                disabled={generating || !prompt.trim()}
                onClick={() => generate("preview")}
                className="key key-ember flex-1 py-2.5 text-[13px] font-semibold flex items-center justify-center gap-2 disabled:opacity-50"
              >
                <Sparkles size={15} />
                {generating ? "Generating Animation with Gemini..." : "Generate Pixel Animation"}
              </button>
            </div>
          </div>

          {/* Right panel: Live 32x32 LED Preview & Export */}
          <div className="flex flex-col items-center justify-between gap-4 p-5 md:col-span-5 bg-chassis-1/50">
            <div className="w-full text-center">
              <div className="engrave !text-[9px] text-ink-3 mb-1">32×32 Hardware Simulation</div>
              <h3 className="text-[13.5px] font-medium text-ink-1">
                {result ? result.title : "Ready for Creation"}
              </h3>
            </div>

            {/* LED Screen Display */}
            {result ? (
              renderLedGrid()
            ) : (
              <div className="flex aspect-square w-full max-w-[280px] flex-col items-center justify-center rounded-[14px] border border-dashed border-line-2 bg-chassis-0 p-6 text-center text-ink-4">
                <Sparkles size={28} className="mb-2 opacity-30 text-ember" />
                <p className="text-[12px]">Type a prompt and click generate.</p>
                <p className="text-[10px] mt-1 text-ink-4">
                  Creates native loops &amp; 32×32 pixel art.
                </p>
              </div>
            )}

            {/* Player Controls (if result available) */}
            {result && result.frames.length > 1 && (
              <div className="flex flex-col w-full gap-2">
                <div className="flex items-center justify-between gap-2 px-1">
                  <span className="engrave !text-[9px] text-ink-3">
                    Frame {currentFrame + 1} / {result.frames.length}
                  </span>
                  <div className="flex items-center gap-1.5">
                    <button
                      className="key key-icon !h-7 !w-7"
                      onClick={() =>
                        setCurrentFrame((prev) => (prev - 1 + result.frames.length) % result.frames.length)
                      }
                      title="Previous frame"
                    >
                      <SkipBack size={12} />
                    </button>
                    <button
                      className="key key-icon !h-7 !w-7"
                      onClick={() => setPlaying(!playing)}
                      title={playing ? "Pause" : "Play"}
                    >
                      {playing ? <Pause size={12} /> : <Play size={12} />}
                    </button>
                    <button
                      className="key key-icon !h-7 !w-7"
                      onClick={() => setCurrentFrame((prev) => (prev + 1) % result.frames.length)}
                      title="Next frame"
                    >
                      <SkipForward size={12} />
                    </button>
                  </div>
                </div>

                {/* Timeline thumbnail scrubber */}
                <div className="flex gap-1 overflow-x-auto p-1 rounded-md bg-chassis-0 border border-line">
                  {result.frames.map((_, idx) => (
                    <button
                      key={idx}
                      onClick={() => {
                        setCurrentFrame(idx);
                        setPlaying(false);
                      }}
                      className={`h-5 min-w-[20px] rounded text-[9px] font-mono transition ${
                        currentFrame === idx
                          ? "bg-ember text-black font-bold"
                          : "bg-chassis-2 text-ink-3 hover:text-ink-1"
                      }`}
                    >
                      {idx + 1}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Quick Action Triggers */}
            {result && (
              <div className="grid grid-cols-2 gap-2 w-full pt-2">
                <button
                  onClick={pushToPanelLoop}
                  className="key key-ember flex items-center justify-center gap-1.5 py-1.5 text-[11.5px]"
                  title="Uploads to the iDotMatrix hardware panel as a native baked loop"
                >
                  <Zap size={12} /> Send to Panel
                </button>
                <button
                  onClick={() => loadFrameToCanvas(currentFrame)}
                  className="key flex items-center justify-center gap-1.5 py-1.5 text-[11.5px]"
                  title="Edit in DotDeck canvas painter"
                >
                  <Brush size={12} /> Edit in Canvas
                </button>
                <a
                  href={result.gif_url}
                  download={`${result.title}.gif`}
                  className="key flex items-center justify-center gap-1.5 py-1.5 text-[11.5px] text-center"
                >
                  <Download size={12} /> Export GIF
                </a>
                <button
                  onClick={async () => {
                    await api.activate("gallery", { media: result.media_id });
                    toast("Saved in Gallery", "ok");
                  }}
                  className="key flex items-center justify-center gap-1.5 py-1.5 text-[11.5px]"
                >
                  <Layers size={12} /> In Gallery
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
