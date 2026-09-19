"use client";

import React, { useState } from "react";
import { DitheringCanvas, PALETTES } from "./DitheringCanvas";
import { DitheringType, DitheringShape } from "@/types";
import { Sliders, Palette, Layers, Sparkles, RefreshCw, Eye } from "lucide-react";

export function DitheringStudio() {
  const [selectedPaletteKey, setSelectedPaletteKey] = useState<keyof typeof PALETTES>("emerald");
  const [ditherType, setDitherType] = useState<DitheringType>("4x4");
  const [shape, setShape] = useState<DitheringShape>("warp");
  const [pixelSize, setPixelSize] = useState<number>(2.5);
  const [speed, setSpeed] = useState<number>(0.4);

  const palette = PALETTES[selectedPaletteKey];

  return (
    <div
      data-agent-id="dithering-studio"
      className="w-full max-w-5xl mx-auto rounded-3xl border border-zinc-800 bg-zinc-950/80 shadow-2xl backdrop-blur-xl overflow-hidden"
    >
      {/* Studio Header */}
      <div className="p-4 sm:p-6 border-b border-zinc-800/80 bg-zinc-900/40 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="p-1 rounded-md bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
              <Sparkles className="w-4 h-4" />
            </span>
            <h3 className="text-base font-semibold text-zinc-100 flex items-center gap-2">
              Paper Design Dithering Shader Studio
            </h3>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-400 border border-zinc-700/60">
              WebGL2 Shaders
            </span>
          </div>
          <p className="text-xs text-zinc-400 mt-1">
            Explore retro Bayer-matrix dithering and visual contrast matrices that power human perception in Abtract.
          </p>
        </div>

        {/* External Link Pill */}
        <a
          href="https://shaders.paper.design"
          target="_blank"
          rel="noopener noreferrer"
          className="text-[11px] font-mono text-emerald-400/90 hover:text-emerald-300 flex items-center gap-1 transition"
        >
          <span>shaders.paper.design</span>
          <span>↗</span>
        </a>
      </div>

      {/* Main Studio Viewport */}
      <div className="relative w-full h-80 sm:h-96 overflow-hidden bg-black flex items-center justify-center">
        {/* The Live Shader Canvas */}
        <DitheringCanvas
          mode="procedural"
          shape={shape}
          type={ditherType}
          size={pixelSize}
          speed={speed}
          scale={0.8}
          colorBack={palette.colorBack}
          colorFront={palette.colorFront}
          colorHighlight={palette.colorHighlight}
          className="w-full h-full"
        />

        {/* Floating Overlay Badge */}
        <div className="absolute top-4 left-4 z-10 px-3 py-1.5 rounded-xl bg-zinc-950/80 border border-zinc-800/80 backdrop-blur-md text-xs font-mono text-zinc-300 flex items-center gap-2 shadow-lg">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping" />
          <span>Matrix: {ditherType}</span>
          <span className="text-zinc-600">|</span>
          <span>Shape: {shape}</span>
          <span className="text-zinc-600">|</span>
          <span>Grid: {pixelSize}px</span>
        </div>

        {/* Center Aesthetic Overlay for Abtract Branding */}
        <div className="absolute inset-0 pointer-events-none flex flex-col items-center justify-center text-center p-6 bg-gradient-to-t from-zinc-950 via-transparent to-transparent">
          <div className="p-3 rounded-2xl bg-zinc-950/70 border border-zinc-800 backdrop-blur-md shadow-2xl max-w-sm">
            <h4 className="text-sm font-bold text-zinc-100 font-mono tracking-tight">
              Abtract Perceptual Filter
            </h4>
            <p className="text-[11px] text-zinc-400 mt-1">
              Transforms complex visual web scenes into quantized affordance maps.
            </p>
          </div>
        </div>
      </div>

      {/* Interactive Controls Bar */}
      <div className="p-4 sm:p-6 bg-zinc-900/30 border-t border-zinc-800/80 grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4 text-xs font-mono">
        {/* Palette Selector */}
        <div className="space-y-1.5">
          <label className="text-[11px] text-zinc-400 font-sans font-medium flex items-center gap-1.5">
            <Palette className="w-3.5 h-3.5 text-zinc-400" /> Color Palette
          </label>
          <select
            value={selectedPaletteKey}
            onChange={(e) => setSelectedPaletteKey(e.target.value as keyof typeof PALETTES)}
            className="w-full px-3 py-2 rounded-xl bg-zinc-950 border border-zinc-800 text-zinc-200 focus:outline-none focus:border-emerald-500/50 cursor-pointer text-xs"
          >
            {Object.entries(PALETTES).map(([key, val]) => (
              <option key={key} value={key}>
                {val.name}
              </option>
            ))}
          </select>
        </div>

        {/* Matrix Type Selector */}
        <div className="space-y-1.5">
          <label className="text-[11px] text-zinc-400 font-sans font-medium flex items-center gap-1.5">
            <Layers className="w-3.5 h-3.5 text-zinc-400" /> Dithering Matrix
          </label>
          <div className="grid grid-cols-4 gap-1 p-1 rounded-xl bg-zinc-950 border border-zinc-800">
            {(["random", "2x2", "4x4", "8x8"] as DitheringType[]).map((t) => (
              <button
                key={t}
                onClick={() => setDitherType(t)}
                className={`py-1 rounded text-center transition cursor-pointer text-[11px] ${
                  ditherType === t
                    ? "bg-emerald-500/20 text-emerald-300 font-bold border border-emerald-500/30"
                    : "text-zinc-500 hover:text-zinc-300"
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>

        {/* Shape Pattern */}
        <div className="space-y-1.5">
          <label className="text-[11px] text-zinc-400 font-sans font-medium flex items-center gap-1.5">
            <Sliders className="w-3.5 h-3.5 text-zinc-400" /> Shape Noise
          </label>
          <select
            value={shape}
            onChange={(e) => setShape(e.target.value as DitheringShape)}
            className="w-full px-3 py-2 rounded-xl bg-zinc-950 border border-zinc-800 text-zinc-200 focus:outline-none focus:border-emerald-500/50 cursor-pointer text-xs"
          >
            {(["warp", "simplex", "dots", "wave", "ripple", "swirl", "sphere"] as DitheringShape[]).map((s) => (
              <option key={s} value={s}>
                {s.charAt(0).toUpperCase() + s.slice(1)}
              </option>
            ))}
          </select>
        </div>

        {/* Pixel Size Slider */}
        <div className="space-y-1.5">
          <div className="flex justify-between items-center text-[11px]">
            <span className="text-zinc-400 font-sans font-medium">Pixel Size</span>
            <span className="text-emerald-400 font-bold">{pixelSize.toFixed(1)}px</span>
          </div>
          <input
            type="range"
            min="1.0"
            max="8.0"
            step="0.5"
            value={pixelSize}
            onChange={(e) => setPixelSize(parseFloat(e.target.value))}
            className="w-full accent-emerald-500 cursor-pointer mt-2"
          />
        </div>
      </div>
    </div>
  );
}
