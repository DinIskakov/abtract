import type { Metadata } from "next";

import { ProductPage } from "@/components/product-page";
import { dashboardMarkup } from "@/content/product-markup";

export const metadata: Metadata = { title: "abtract dashboard" };

export default function DashboardPage() {
  return (
    <ProductPage
      bodyClass="dashboard"
      html={dashboardMarkup}
      script="/scripts/dashboard.js"
      chartJs
    />
  );
}
