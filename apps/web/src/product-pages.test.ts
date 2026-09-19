import { describe, expect, it } from "bun:test";

import { dashboardMarkup, jobMarkup, landingMarkup } from "./content/product-markup";

describe("product pages", () => {
  it("keeps the browser hooks required by each migrated route", () => {
    expect(landingMarkup).toContain('id="intake"');
    expect(landingMarkup).toContain('id="scan-mode"');
    expect(dashboardMarkup).toContain('id="site-select"');
    expect(dashboardMarkup).toContain('id="heatmap"');
    expect(jobMarkup).toContain('id="live-preview"');
    expect(jobMarkup).toContain('id="report"');
  });
});
