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
import { GanttChartDto, GanttRowDto } from '../../../core/models/maintenance-chart.model';

/**
 * visualization.md §5 -- "Maintenance Gantt chart", persona Reza
 * (defensible budget visualization). Data "generated directly from the
 * CP-SAT solver output... not maintained as a separate planning
 * artifact" -- komponen ini MURNI menampilkan MaintenanceSchedule apa
 * adanya (via MaintenanceGanttChartService backend), tidak ada state
 * Gantt lokal.
 *
 * Palet warna CS1-CS5 (visualization.md §3, FIXED) reuse persis --
 * konsisten dengan render.js server-side (exports.md §2, PDF export)
 * dan condition-trend-chart (Fase 1).
 */
const CS_COLOR: Record<string, string> = {
  CS1: '#2E7D32',
  CS2: '#2E7D32',
  CS3: '#F9A825',
  CS4: '#C62828',
  CS5: '#C62828',
};

@Component({
  selector: 'app-gantt-chart',
  standalone: true,
  templateUrl: './gantt-chart.component.html',
  styleUrl: './gantt-chart.component.scss',
})
export class GanttChartComponent implements AfterViewInit, OnDestroy {
  private readonly chartService = inject(MaintenanceChartService);
  private readonly destroyRef = inject(DestroyRef);

  readonly organizationId = input.required<string>();
  readonly runId = input.required<string>();

  @ViewChild('chartContainer', { static: true })
  private chartContainer!: ElementRef<HTMLDivElement>;

  readonly loading = signal(true);
  readonly errorMessage = signal<string | null>(null);
  readonly chartData = signal<GanttChartDto | null>(null);

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
      .getGanttChart(this.organizationId(), this.runId())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (data) => {
          this.chartData.set(data);
          this.loading.set(false);
        },
        error: (err) => {
          this.errorMessage.set(
            'Jadwal pemeliharaan tidak dapat dimuat. Coba muat ulang halaman.',
          );
          this.loading.set(false);
          console.error('Gagal memuat Gantt chart', err);
        },
      });
  }

  private renderChart(data: GanttChartDto): void {
    this.plotFigure?.remove();
    this.plotFigure = null;

    if (data.rows.length === 0) {
      return;
    }

    // Clamp lebar minimum -- mencegah luas area plot negatif saat
    // container lebih sempit dari marginLeft (terbukti terjadi nyata:
    // clientWidth 132px saat panel DevTools terbuka menyempitkan viewport,
    // menghasilkan error render "<rect> width -108" karena
    // marginLeft:220 > width). 400px adalah lebar minimum praktis supaya
    // label komponen + beberapa tahun tetap terbaca.
    const measuredWidth = this.chartContainer.nativeElement.clientWidth || 640;
    const width = Math.max(measuredWidth, 400);

    // x2 = tahun mulai + durasi (dari duration_years) -- lebar minimum
    // 0.15 tahun supaya bar tetap terlihat untuk intervensi berdurasi
    // sangat pendek (pola sama render.js server-side).
    const rows = data.rows.map((r) => ({
      ...r,
      x1: r.scheduled_year,
      x2: r.scheduled_year + Math.max(r.duration_years, 0.15),
    }));

    const componentLabels = [...new Set(rows.map((r) => r.component_label))];

    const figure = Plot.plot({
      width,
      height: Math.max(120, componentLabels.length * 32 + 60),
      marginLeft: 220,
      marginBottom: 36,
      x: { label: 'Tahun', tickFormat: 'd' },
      y: { label: null, domain: componentLabels },
      marks: [
        Plot.gridX({ stroke: 'currentColor', strokeOpacity: 0.08 }),
        Plot.barX(rows, {
          x1: 'x1',
          x2: 'x2',
          y: 'component_label',
          fill: (r: GanttRowDto) => CS_COLOR[r.expected_state_after] ?? '#999999',
          // Tooltip via elemen <title> SVG native (dirender browser
          // sebagai tooltip OS bawaan saat hover) -- lebih reliabel
          // daripada Plot.tip/Plot.pointer, yang terbukti menghasilkan
          // error rendering (<rect> width negatif) dan tooltip yang
          // tidak pernah muncul saat diuji manual di browser.
          title: (r: GanttRowDto) =>
            `${r.intervention_name}\nTahun: ${r.scheduled_year}\n` +
            `Biaya: Rp ${Number(r.cost).toLocaleString('id-ID')}\n` +
            `Kondisi setelah: ${r.expected_state_after}`,
        }),
      ],
    });

    this.plotFigure = figure;
    this.chartContainer.nativeElement.appendChild(figure);
  }
}
