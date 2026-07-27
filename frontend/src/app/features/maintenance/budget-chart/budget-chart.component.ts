import {
  AfterViewInit,
  Component,
  DestroyRef,
  ElementRef,
  OnDestroy,
  ViewChild,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import * as Plot from '@observablehq/plot';
import { MaintenanceChartService } from '../../../core/services/maintenance-chart.service';
import { BudgetChartDto, BudgetYearDto } from '../../../core/models/maintenance-chart.model';

/**
 * visualization.md §5 -- "Budget allocation bar chart", persona Manager
 * (at-a-glance budget utilization). Data dari MaintenanceBudgetChartService
 * backend -- allocated_cost per tahun (Sum MaintenanceSchedule.cost) vs
 * Budget_t (flat atau budget_profile custom, scheduling.md §3.1).
 *
 * cost/budget dikonversi Number() HANYA di titik render chart (posisi
 * pixel) -- DTO tetap menyimpan string asli (lihat maintenance-chart.model.ts).
 */
@Component({
  selector: 'app-budget-chart',
  standalone: true,
  templateUrl: './budget-chart.component.html',
  styleUrl: './budget-chart.component.scss',
})
export class BudgetChartComponent implements AfterViewInit, OnDestroy {
  private readonly chartService = inject(MaintenanceChartService);
  private readonly destroyRef = inject(DestroyRef);

  readonly organizationId = input.required<string>();
  readonly runId = input.required<string>();

  @ViewChild('chartContainer', { static: true })
  private chartContainer!: ElementRef<HTMLDivElement>;

  readonly loading = signal(true);
  readonly errorMessage = signal<string | null>(null);
  readonly chartData = signal<BudgetChartDto | null>(null);

  private plotFigure: ReturnType<typeof Plot.plot> | null = null;
  private resizeObserver?: ResizeObserver;

  constructor() {
    effect(() => {
      const data = this.chartData();
      if (data) {
        this.renderChart(data);
      }
    });
  }

  ngAfterViewInit(): void {
    this.fetchData();

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
      .getBudgetChart(this.organizationId(), this.runId())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (data) => {
          this.chartData.set(data);
          this.loading.set(false);
        },
        error: (err) => {
          this.errorMessage.set(
            'Alokasi anggaran tidak dapat dimuat. Coba muat ulang halaman.',
          );
          this.loading.set(false);
          console.error('Gagal memuat budget chart', err);
        },
      });
  }

  private renderChart(data: BudgetChartDto): void {
    this.plotFigure?.remove();
    this.plotFigure = null;

    if (data.years.length === 0) {
      return;
    }

    // Clamp lebar minimum -- guard yang sama seperti gantt-chart.component.ts,
    // diterapkan konsisten meski marginLeft di sini (64) jauh lebih kecil
    // dan lebih jarang memicu kasus negatif.
    const measuredWidth = this.chartContainer.nativeElement.clientWidth || 640;
    const width = Math.max(measuredWidth, 400);

    const bars = data.years.map((y: BudgetYearDto) => ({
      year: y.year,
      cost: Number(y.allocated_cost),
    }));
    const budgetLine = data.years.map((y: BudgetYearDto) => ({
      year: y.year,
      budget: Number(y.budget),
    }));

    const figure = Plot.plot({
      width,
      height: 320,
      marginLeft: 64,
      marginBottom: 36,
      x: { label: 'Tahun', tickFormat: 'd' },
      y: { label: 'Rupiah', grid: true },
      marks: [
        Plot.barY(bars, {
          x: 'year',
          y: 'cost',
          fill: '#2E7D32',
          // Tooltip via elemen <title> SVG native -- lihat rationale
          // di gantt-chart.component.ts (Plot.tip/Plot.pointer terbukti
          // tidak reliabel: error render + tooltip tidak pernah muncul).
          title: (d: { year: number; cost: number }) =>
            `Tahun ${d.year}\nAlokasi: Rp ${d.cost.toLocaleString('id-ID')}`,
        }),
        Plot.line(budgetLine, {
          x: 'year',
          y: 'budget',
          stroke: '#C62828',
          strokeWidth: 2,
          strokeDasharray: '4,3',
        }),
      ],
    });

    this.plotFigure = figure;
    this.chartContainer.nativeElement.appendChild(figure);
  }
}
