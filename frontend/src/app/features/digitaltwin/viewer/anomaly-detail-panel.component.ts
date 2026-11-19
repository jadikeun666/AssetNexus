import { DatePipe } from '@angular/common';
import {
  AfterViewInit,
  Component,
  ElementRef,
  OnDestroy,
  ViewChild,
  computed,
  effect,
  input,
  output,
} from '@angular/core';
import * as Plot from '@observablehq/plot';

import { AnomalyEventDetailDto, SensorTraceDto } from '../../../core/models/digital-twin.model';
import { detectionMethodLabel, severityLabel, severityToColor } from './anomaly-marker-math';
import { DIGITAL_TWIN } from './digital-twin.constants';

export type PanelStatus = 'loading' | 'ready' | 'error';

/**
 * visualization.md §6: panel detail saat anomaly marker diklik -- daftar
 * event komponen (hanya baca) + grafik sensor trace di sekitar event
 * terpilih. Komponen PRESENTASI: viewer yang mengambil data dan memegang
 * state; panel hanya menampilkan dan memancarkan closed / eventSelected.
 */
@Component({
  selector: 'app-anomaly-detail-panel',
  standalone: true,
  imports: [DatePipe],
  templateUrl: './anomaly-detail-panel.component.html',
  styleUrl: './anomaly-detail-panel.component.scss',
})
export class AnomalyDetailPanelComponent implements AfterViewInit, OnDestroy {
  readonly componentType = input.required<string>();
  readonly worstSeverity = input.required<string>();
  readonly events = input.required<AnomalyEventDetailDto[]>();
  readonly eventsStatus = input<PanelStatus>('loading');
  readonly selectedAnomalyId = input<string | null>(null);
  readonly trace = input<SensorTraceDto | null>(null);
  readonly traceStatus = input<PanelStatus>('loading');

  readonly closed = output<void>();
  readonly eventSelected = output<string>();

  // Dipakai template (fungsi impor tidak bisa dipanggil langsung di template).
  readonly severityLabel = severityLabel;
  readonly methodLabel = detectionMethodLabel;
  readonly severityColor = severityToColor;
  readonly halfWindowMinutes = DIGITAL_TWIN.ANOMALY_TRACE_HALF_WINDOW_MINUTES;

  readonly accentColor = computed(() => severityToColor(this.worstSeverity()));
  readonly selectedEvent = computed(
    () => this.events().find((e) => e.anomaly_id === this.selectedAnomalyId()) ?? null,
  );
  readonly traceSummary = computed(() => {
    const readings = this.trace()?.readings ?? [];
    if (readings.length === 0) return 'Belum ada grafik pembacaan sensor';
    const values = readings.map((r) => r.value);
    return (
      `Grafik ${readings.length} pembacaan sensor, nilai ${Math.min(...values)} ` +
      `sampai ${Math.max(...values)} ${readings[0].unit}`
    );
  });

  @ViewChild('heading', { static: true }) private heading?: ElementRef<HTMLElement>;
  @ViewChild('traceContainer', { static: true }) private traceContainer?: ElementRef<HTMLDivElement>;
  private plotFigure: ReturnType<typeof Plot.plot> | null = null;

  constructor() {
    effect(() => this.renderTrace(this.trace(), this.selectedEvent()));
  }

  ngAfterViewInit(): void {
    // Fokus ke judul saat panel muncul (keyboard/screen reader); render
    // ulang karena effect pertama bisa jalan sebelum container ada.
    this.heading?.nativeElement.focus();
    this.renderTrace(this.trace(), this.selectedEvent());
  }

  ngOnDestroy(): void {
    this.plotFigure?.remove();
  }

  // shortcut: grafik tidak dirender ulang saat lebar panel berubah; upgrade
  // (ResizeObserver, pola condition-trend-chart) bila panel dibuat resizable.
  private renderTrace(trace: SensorTraceDto | null, selected: AnomalyEventDetailDto | null): void {
    const container = this.traceContainer?.nativeElement;
    if (!container) return;

    this.plotFigure?.remove();
    this.plotFigure = null;
    if (!trace || trace.readings.length === 0) return;

    const data = trace.readings.map((r) => ({ time: new Date(r.timestamp), value: r.value }));
    const figure = Plot.plot({
      width: container.clientWidth || 340,
      height: 220,
      marginLeft: 48,
      x: { type: 'time', label: null },
      y: { label: trace.readings[0].unit },
      marks: [
        Plot.gridY({ stroke: 'currentColor', strokeOpacity: 0.08 }),
        Plot.lineY(data, { x: 'time', y: 'value', stroke: '#142A45', strokeWidth: 1.5 }),
        Plot.dot(data, { x: 'time', y: 'value', fill: '#142A45', r: 2 }),
        ...(selected
          ? [
              Plot.ruleX([new Date(selected.detected_at)], {
                stroke: severityToColor(selected.severity),
                strokeWidth: 2,
              }),
            ]
          : []),
        Plot.tip(data, Plot.pointer({ x: 'time', y: 'value' })),
      ],
    });

    this.plotFigure = figure;
    container.appendChild(figure);
  }
}
