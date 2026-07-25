import {
  AfterViewInit,
  Component,
  DestroyRef,
  ElementRef,
  OnDestroy,
  ViewChild,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import * as Plot from '@observablehq/plot';
import { DeteriorationChartService } from '../../../core/services/deterioration-chart.service';
import { ComponentForecastChartDto } from '../../../core/models/forecast-chart.model';

/**
 * visualization.md §5 -- chart "Condition trend line" untuk persona
 * Dr. Wibowo (model transparency). Band fuzzy (§4.3) WAJIB tampil kalau
 * tersedia -- lihat computed hasConfidenceBand di bawah, tidak pernah
 * disembunyikan/disederhanakan.
 *
 * Garis batas horizontal (90/70/50/25) merujuk skala condition_score
 * (asset-registry.md §3.1) -- konteks struktural untuk pembaca, bukan
 * dekorasi.
 */
@Component({
  selector: 'app-condition-trend-chart',
  standalone: true,
  templateUrl: './condition-trend-chart.component.html',
  styleUrl: './condition-trend-chart.component.scss',
})
export class ConditionTrendChartComponent implements AfterViewInit, OnDestroy {
  private readonly chartService = inject(DeteriorationChartService);
  private readonly destroyRef = inject(DestroyRef);

  readonly organizationId = input.required<string>();
  readonly componentId = input.required<string>();

  @ViewChild('chartContainer', { static: true })
  private chartContainer!: ElementRef<HTMLDivElement>;

  readonly loading = signal(true);
  readonly errorMessage = signal<string | null>(null);
  readonly chartData = signal<ComponentForecastChartDto | null>(null);

  readonly hasConfidenceBand = computed(() =>
    (this.chartData()?.points ?? []).some((p) => p.confidence_lower !== null),
  );

  readonly modelLabel = computed(() => {
    switch (this.chartData()?.model_type) {
      case 'discrete_markov':
        return 'Model dasar (DTMC)';
      case 'ctmc_latent':
      case 'fuzzy_markov':
        return 'Model lanjutan (CTMC + Fuzzy)';
      default:
        return 'Belum ada model';
    }
  });

  private plotFigure: ReturnType<typeof Plot.plot> | null = null;
  private resizeObserver?: ResizeObserver;

  constructor() {
    // Re-render otomatis setiap kali chartData berubah (mis. setelah
    // fetch selesai) -- pola signal + effect, bukan manual subscribe
    // callback yang langsung memanggil renderChart.
    effect(() => {
      const data = this.chartData();
      if (data) {
        this.renderChart(data);
      }
    });
  }

  ngAfterViewInit(): void {
    this.fetchData();

    // Observable Plot tidak auto-responsive -- re-render manual saat
    // container berubah ukuran (mis. sidebar dashboard dibuka/tutup).
    this.resizeObserver = new ResizeObserver(() => {
      const data = this.chartData();
      if (data) this.renderChart(data);
    });
    this.resizeObserver.observe(this.chartContainer.nativeElement);
  }

  ngOnDestroy(): void {
    this.resizeObserver?.disconnect();
    this.plotFigure?.remove();
  }

  private fetchData(): void {
    this.loading.set(true);
    this.errorMessage.set(null);

    this.chartService
      .getForecastChart(this.organizationId(), this.componentId())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (data) => {
          this.chartData.set(data);
          this.loading.set(false);
        },
        error: (err) => {
          this.errorMessage.set(
            'Prakiraan kondisi tidak dapat dimuat. Coba muat ulang halaman.',
          );
          this.loading.set(false);
          console.error('Gagal memuat forecast chart', err);
        },
      });
  }

  private renderChart(data: ComponentForecastChartDto): void {
    this.plotFigure?.remove();
    this.plotFigure = null;

    if (data.points.length === 0) {
      return;
    }

    const width = this.chartContainer.nativeElement.clientWidth || 640;

    const marks = [
      Plot.gridY({ stroke: 'currentColor', strokeOpacity: 0.08 }),
      // Garis batas CS1-CS5 (asset-registry.md §3.1) -- konteks struktural.
      Plot.ruleY([90, 70, 50, 25], {
        stroke: '#94A3B8',
        strokeDasharray: '2,3',
        strokeOpacity: 0.6,
      }),
    ];

    if (this.hasConfidenceBand()) {
      marks.push(
        Plot.areaY(data.points, {
          x: 'forecast_year',
          y1: 'confidence_lower',
          y2: 'confidence_upper',
          fill: '#142A45',
          fillOpacity: 0.12,
        }),
      );
    }

    marks.push(
      Plot.lineY(data.points, {
        x: 'forecast_year',
        y: 'condition_score',
        stroke: '#142A45',
        strokeWidth: 2,
      }),
      Plot.dot(data.points, {
        x: 'forecast_year',
        y: 'condition_score',
        fill: '#142A45',
        r: 2.5,
      }),
      Plot.tip(
        data.points,
        Plot.pointer({
          x: 'forecast_year',
          y: 'condition_score',
          title: (d: (typeof data.points)[number]) =>
            `Tahun ${d.forecast_year}\nSkor kondisi: ${d.condition_score.toFixed(1)}` +
            (d.confidence_lower !== null
              ? `\nBand: ${d.confidence_lower!.toFixed(1)} – ${d.confidence_upper!.toFixed(1)}`
              : ''),
        }),
      ),
    );

    const figure = Plot.plot({
      width,
      height: 320,
      marginLeft: 48,
      marginBottom: 36,
      x: { label: 'Tahun', tickFormat: 'd' },
      y: { label: 'Skor kondisi (0–100)', domain: [0, 100] },
      marks,
    });

    this.plotFigure = figure;
    this.chartContainer.nativeElement.appendChild(figure);
  }
}
