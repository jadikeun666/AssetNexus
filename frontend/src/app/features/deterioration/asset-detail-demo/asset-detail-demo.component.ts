import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ConditionTrendChartComponent } from '../condition-trend-chart/condition-trend-chart.component';
import { GanttChartComponent } from '../../maintenance/gantt-chart/gantt-chart.component';
import { BudgetChartComponent } from '../../maintenance/budget-chart/budget-chart.component';

/**
 * Halaman DEMO/VERIFIKASI MANUAL sementara -- bukan bagian permanen
 * arsitektur produk. Diperluas sesi Fase 2 (chart Gantt + budget) dengan
 * pola identik field organizationId/componentId yang sudah ada -- tambah
 * runId untuk MaintenanceGanttChartService/MaintenanceBudgetChartService.
 *
 * HAPUS/ganti komponen ini begitu ada halaman asset-detail sungguhan.
 */
@Component({
  selector: 'app-asset-detail-demo',
  standalone: true,
  imports: [
    FormsModule,
    ConditionTrendChartComponent,
    GanttChartComponent,
    BudgetChartComponent,
  ],
  template: `
    <div class="demo-page">
      <h2>Demo Verifikasi Manual — Condition Trend Chart</h2>
      <p class="demo-page__hint">
        Isi UUID organisasi dan komponen dari database dev kamu (lihat data
        yang dibuat test_chart_service.py, atau buat baru lewat Django
        shell), lalu klik "Muat Chart".
      </p>
      <div class="demo-page__form">
        <label>
          Organization ID
          <input
            type="text"
            [(ngModel)]="organizationIdInput"
            placeholder="uuid organisasi"
          />
        </label>
        <label>
          Component ID
          <input
            type="text"
            [(ngModel)]="componentIdInput"
            placeholder="uuid asset component"
          />
        </label>
        <button (click)="loadChart()">Muat Chart</button>
      </div>
      @if (activeOrgId() && activeComponentId()) {
        <app-condition-trend-chart
          [organizationId]="activeOrgId()!"
          [componentId]="activeComponentId()!"
        />
      } @else {
        <p class="demo-page__hint">Isi form di atas dulu untuk memuat chart.</p>
      }

      <hr class="demo-page__divider" />

      <h2>Demo Verifikasi Manual — Gantt &amp; Budget Chart (Fase 2)</h2>
      <p class="demo-page__hint">
        Isi UUID organisasi (bisa sama dengan di atas) dan UUID
        OptimizationRun, lalu klik "Muat Chart Pemeliharaan".
      </p>
      <div class="demo-page__form">
        <label>
          Organization ID
          <input
            type="text"
            [(ngModel)]="organizationIdInput2"
            placeholder="uuid organisasi"
          />
        </label>
        <label>
          Optimization Run ID
          <input
            type="text"
            [(ngModel)]="runIdInput"
            placeholder="uuid optimization run"
          />
        </label>
        <button (click)="loadMaintenanceCharts()">Muat Chart Pemeliharaan</button>
      </div>
      @if (activeOrgId2() && activeRunId()) {
        <app-gantt-chart [organizationId]="activeOrgId2()!" [runId]="activeRunId()!" />
        <app-budget-chart [organizationId]="activeOrgId2()!" [runId]="activeRunId()!" />
      } @else {
        <p class="demo-page__hint">Isi form di atas dulu untuk memuat chart pemeliharaan.</p>
      }
    </div>
  `,
  styles: [
    `
      .demo-page {
        max-width: 720px;
        margin: 2rem auto;
        padding: 0 1rem;
        font-family: 'Inter', system-ui, sans-serif;
      }
      .demo-page__hint {
        font-size: 0.85rem;
        color: #64748b;
      }
      .demo-page__divider {
        margin: 2rem 0;
        border: none;
        border-top: 1px solid #e2e8f0;
      }
      .demo-page__form {
        display: flex;
        gap: 0.75rem;
        align-items: flex-end;
        margin-bottom: 1.5rem;
        flex-wrap: wrap;
      }
      .demo-page__form label {
        display: flex;
        flex-direction: column;
        font-size: 0.75rem;
        color: #142a45;
        gap: 0.25rem;
      }
      .demo-page__form input {
        padding: 0.4rem 0.5rem;
        border: 1px solid #cbd5e1;
        border-radius: 4px;
        min-width: 260px;
        font-family: 'IBM Plex Mono', ui-monospace, monospace;
        font-size: 0.8rem;
      }
      .demo-page__form button {
        padding: 0.45rem 1rem;
        border: none;
        border-radius: 4px;
        background: #142a45;
        color: white;
        cursor: pointer;
        font-size: 0.85rem;
      }
    `,
  ],
})
export class AssetDetailDemoComponent {
  organizationIdInput = '';
  componentIdInput = '';
  readonly activeOrgId = signal<string | null>(null);
  readonly activeComponentId = signal<string | null>(null);

  organizationIdInput2 = '';
  runIdInput = '';
  readonly activeOrgId2 = signal<string | null>(null);
  readonly activeRunId = signal<string | null>(null);

  loadChart(): void {
    this.activeOrgId.set(this.organizationIdInput.trim() || null);
    this.activeComponentId.set(this.componentIdInput.trim() || null);
  }

  loadMaintenanceCharts(): void {
    this.activeOrgId2.set(this.organizationIdInput2.trim() || null);
    this.activeRunId.set(this.runIdInput.trim() || null);
  }
}
