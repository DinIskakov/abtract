export type ViewMode = 'human' | 'agent';

export type ModelType = 'claude-3-7-sonnet' | 'gemini-2-5-flash' | 'gpt-4o';

export interface ModelOption {
  id: ModelType;
  name: string;
  provider: string;
  badge: string;
  defaultSuccessA: number; // e.g. 42%
  defaultSuccessB: number; // e.g. 96%
  tokenCostRatio: string;
  avatarColor: string;
}

export type DitheringType = 'random' | '2x2' | '4x4' | '8x8';
export type DitheringShape = 'warp' | 'simplex' | 'dots' | 'wave' | 'ripple' | 'swirl' | 'sphere';

export interface ColorPalette {
  name: string;
  colorBack: string;
  colorFront: string;
  colorHighlight?: string;
}

export interface Affordance {
  element_id: string;
  tag_name: string;
  role: string;
  accessible_name: string;
  css_selector: string;
  bounding_box: { x: number; y: number; width: number; height: number };
  data_agent_id?: string;
  data_agent_action?: string;
  aria_live?: string;
}

export interface BenchmarkStep {
  stepIndex: number;
  phase: 'PERCEPTION' | 'PLANNING' | 'DISPATCH' | 'EVALUATION';
  description: string;
  variantA: {
    state: string;
    tokens: number;
    friction?: string;
    reasoning: string;
    success: boolean;
  };
  variantB: {
    state: string;
    tokens: number;
    friction?: string;
    reasoning: string;
    success: boolean;
  };
}
