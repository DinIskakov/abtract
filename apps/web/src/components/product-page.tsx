"use client";

import Script from "next/script";
import { useEffect, useState } from "react";

type ProductPageProps = {
  bodyClass: string;
  html: string;
  script: string;
  chartJs?: boolean;
};

export function ProductPage({ bodyClass, html, script, chartJs = false }: ProductPageProps) {
  const [chartReady, setChartReady] = useState(!chartJs);

  useEffect(() => {
    document.body.className = bodyClass;
    return () => {
      document.body.className = "";
    };
  }, [bodyClass]);

  return (
    <>
      <div dangerouslySetInnerHTML={{ __html: html }} />
      {chartJs ? (
        <Script
          src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"
          strategy="afterInteractive"
          onLoad={() => setChartReady(true)}
        />
      ) : null}
      {chartReady ? <Script src={script} strategy="afterInteractive" /> : null}
    </>
  );
}
