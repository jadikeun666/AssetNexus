import { JSDOM } from "jsdom";
import * as Plot from "@observablehq/plot";

// visualization.md §3: palet heatmap CS1-CS5 FIXED, dipakai ulang di sini
// supaya bahasa visual konsisten dengan chart Fase 1 dan viewer 3D nanti.
const CS_COLOR = {
  CS1: "#2E7D32",
  CS2: "#2E7D32",
  CS3: "#F9A825",
  CS4: "#C62828",
  CS5: "#C62828",
};

function renderGantt(data, document) {
  const rows = data.rows.map((r) => ({
    ...r,
    x1: r.scheduled_year,
    x2: r.scheduled_year + Math.max(r.duration_years, 0.15), // lebar minimum
    // supaya bar tetap kelihatan untuk intervensi berdurasi sangat pendek
    color: CS_COLOR[r.expected_state_after] || "#999999",
  }));

  return Plot.plot({
    document,
    marginLeft: 220,
    width: 900,
    height: Math.max(120, rows.length * 28 + 60),
    x: { label: "Tahun" },
    y: { label: null, domain: [...new Set(rows.map((r) => r.component_label))] },
    marks: [
      Plot.barX(rows, {
        x1: "x1",
        x2: "x2",
        y: "component_label",
        fill: "color",
        title: (r) => `${r.intervention_name} (${r.scheduled_year})`,
      }),
      Plot.text(rows, {
        x: "x1",
        y: "component_label",
        text: (r) => r.intervention_name,
        dx: 4,
        dy: -10,
        fontSize: 9,
      }),
    ],
  });
}

function renderBudget(data, document) {
  const years = data.years;
  const bars = years.map((y) => ({ year: y.year, cost: Number(y.allocated_cost) }));
  const budgetLine = years.map((y) => ({ year: y.year, budget: Number(y.budget) }));

  return Plot.plot({
    document,
    width: 700,
    height: 350,
    x: { label: "Tahun", tickFormat: "d" },
    y: { label: "Rupiah", grid: true },
    marks: [
      Plot.barY(bars, { x: "year", y: "cost", fill: "#2E7D32" }),
      Plot.line(budgetLine, {
        x: "year",
        y: "budget",
        stroke: "#C62828",
        strokeWidth: 2,
        strokeDasharray: "4,3",
      }),
    ],
  });
}

// asset-registry.md §3.1: batas skor tampilan CS1-CS5 (garis referensi),
// persis nilai yang dipakai komponen Angular condition-trend-chart Fase 1.
const CS_BOUNDARIES = [
  { state: "CS1/CS2", score: 90 },
  { state: "CS2/CS3", score: 70 },
  { state: "CS3/CS4", score: 50 },
  { state: "CS4/CS5", score: 25 },
];

function renderConditionTrend(data, document) {
  const points = data.points;
  const hasConfidenceBand = points.some(
    (p) => p.confidence_lower !== null && p.confidence_upper !== null
  );

  const marks = [];

  // visualization.md §5 / formulas.md §3.2: shaded confidence band --
  // disembunyikan otomatis kalau tidak ada bound (model DTMC), sama
  // logic hasConfidenceBand di komponen Angular Fase 1.
  if (hasConfidenceBand) {
    marks.push(
      Plot.areaY(points, {
        x: "forecast_year",
        y1: "confidence_lower",
        y2: "confidence_upper",
        fill: "#2E7D32",
        fillOpacity: 0.15,
      })
    );
  }

  // Garis referensi batas CS1-CS5 (asset-registry.md §3.1), putus-putus,
  // sebagai konteks struktural -- bukan data forecast.
  for (const boundary of CS_BOUNDARIES) {
    marks.push(
      Plot.ruleY([boundary.score], {
        stroke: "#999999",
        strokeDasharray: "3,3",
        strokeWidth: 1,
      })
    );
  }

  marks.push(
    Plot.line(points, {
      x: "forecast_year",
      y: "condition_score",
      stroke: "#2E7D32",
      strokeWidth: 2,
    }),
    Plot.dot(points, {
      x: "forecast_year",
      y: "condition_score",
      fill: "#2E7D32",
      r: 3,
    })
  );

  return Plot.plot({
    document,
    width: 700,
    height: 300,
    x: { label: "Tahun" },
    y: { label: "Skor Kondisi", domain: [0, 100] },
    marks,
  });
}

async function main() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  const input = JSON.parse(Buffer.concat(chunks).toString("utf-8"));

  const jsdom = new JSDOM("");
  const document = jsdom.window.document;

  let plot;
  if (input.chart_type === "gantt") {
    plot = renderGantt(input.data, document);
  } else if (input.chart_type === "budget") {
    plot = renderBudget(input.data, document);
  } else if (input.chart_type === "condition_trend") {
    plot = renderConditionTrend(input.data, document);
  } else {
    throw new Error(`chart_type tidak dikenal: ${input.chart_type}`);
  }

  process.stdout.write(plot.outerHTML);
}

main().catch((err) => {
  console.error(err.stack || String(err));
  process.exit(1);
});
