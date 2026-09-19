"use client";

import React, { useState, useRef, useSyncExternalStore } from "react";
import dynamic from "next/dynamic";
import { DitheringType, DitheringShape } from "@/types";

const emptySubscribe = () => () => {};

// Dynamic import of Dithering and ImageDithering from @paper-design/shaders-react
// with ssr: false so it never executes during SSR / hydration
const DynamicDithering = dynamic(
  () => import("@paper-design/shaders-react").then((mod) => mod.Dithering),
  {
    ssr: false,
    loading: () => <ShaderFallback colorBack="#09090b" colorFront="#00f0ff" />,
  }
);

const DynamicImageDithering = dynamic(
  () => import("@paper-design/shaders-react").then((mod) => mod.ImageDithering),
  {
    ssr: false,
    loading: () => <ShaderFallback colorBack="#09090b" colorFront="#00f0ff" />,
  }
);

interface DitheringCanvasProps {
  mode?: "procedural" | "image";
  imageSrc?: string;
  shape?: DitheringShape;
  type?: DitheringType;
  size?: number;
  speed?: number;
  scale?: number;
  colorBack?: string;
  colorFront?: string;
  colorHighlight?: string;
  className?: string;
  interactive?: boolean;
}

export const PALETTES = {
  emerald: {
    name: "Cyber Emerald",
    colorBack: "#050d0a",
    colorFront: "#10b981",
    colorHighlight: "#34d399",
  },
  cyan: {
    name: "Quantum Cyan",
    colorBack: "#030b14",
    colorFront: "#06b6d4",
    colorHighlight: "#38bdf8",
  },
  amber: {
    name: "Phosphor Amber",
    colorBack: "#100902",
    colorFront: "#f59e0b",
    colorHighlight: "#fbbf24",
  },
  obsidian: {
    name: "Monochrome Obsidian",
    colorBack: "#09090b",
    colorFront: "#f4f4f5",
    colorHighlight: "#a1a1aa",
  },
  violet: {
    name: "Ultraviolet",
    colorBack: "#0a0414",
    colorFront: "#a855f7",
    colorHighlight: "#c084fc",
  },
};

function ShaderFallback({ colorBack, colorFront }: { colorBack: string; colorFront: string }) {
  return (
    <div
      className="w-full h-full relative overflow-hidden"
      style={{ backgroundColor: colorBack }}
    >
      <div
        className="absolute inset-0 opacity-20"
        style={{
          backgroundImage: `radial-gradient(${colorFront} 1px, transparent 1px)`,
          backgroundSize: "8px 8px",
        }}
      />
    </div>
  );
}

export function DitheringCanvas({
  mode = "procedural",
  imageSrc,
  shape = "warp",
  type = "4x4",
  size = 2.5,
  speed = 0.5,
  scale = 0.8,
  colorBack = "#050d0a",
  colorFront = "#10b981",
  colorHighlight = "#34d399",
  className = "",
  interactive = true,
}: DitheringCanvasProps) {
  const isClient = useSyncExternalStore(
    emptySubscribe,
    () => true,
    () => false
  );
  const [hasError, setHasError] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  if (!isClient || hasError) {
    return (
      <div className={`relative w-full h-full overflow-hidden ${className}`}>
        <ShaderFallback colorBack={colorBack} colorFront={colorFront} />
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className={`relative w-full h-full overflow-hidden ${className}`}
      style={{ minHeight: "200px" }}
    >
      <div className="absolute inset-0 w-full h-full pointer-events-none">
        {mode === "image" && imageSrc ? (
          <DynamicImageDithering
            image={imageSrc}
            type={type}
            size={size}
            colorBack={colorBack}
            colorFront={colorFront}
            colorHighlight={colorHighlight}
            style={{ width: "100%", height: "100%" }}
            onError={() => setHasError(true)}
          />
        ) : (
          <DynamicDithering
            shape={shape}
            type={type}
            size={size}
            speed={interactive ? speed : 0}
            scale={scale}
            colorBack={colorBack}
            colorFront={colorFront}
            style={{ width: "100%", height: "100%" }}
            onError={() => setHasError(true)}
          />
        )}
      </div>
    </div>
  );
}
