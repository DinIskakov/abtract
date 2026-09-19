import type { Metadata } from "next";

import { ProductPage } from "@/components/product-page";
import { jobMarkup } from "@/content/product-markup";

export const metadata: Metadata = { title: "abtract — job" };

export default function JobPage() {
  return <ProductPage bodyClass="product" html={jobMarkup} script="/scripts/job.js" />;
}
