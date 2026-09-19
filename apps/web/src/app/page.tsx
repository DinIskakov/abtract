import type { Metadata } from "next";

import { ProductPage } from "@/components/product-page";
import { landingMarkup } from "@/content/product-markup";

export const metadata: Metadata = {
  title: "abtract — Evolve the environment",
  description: "Test your website with a swarm of AI agents, measure outcomes, and evolve the environment.",
};

export default function Home() {
  return <ProductPage bodyClass="product landing-page" html={landingMarkup} script="/scripts/landing.js" />;
}
