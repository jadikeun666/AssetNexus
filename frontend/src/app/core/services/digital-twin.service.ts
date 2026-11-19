import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  AnomalyEventDetailDto,
  AnomalyMarkerDto,
  AssetAlertsPayload,
  DigitalTwinUploadResponseDto,
  MaintenanceMarkerDto,
  SensorTraceDto,
  ViewerPayloadDto,
} from '../models/digital-twin.model';

@Injectable({ providedIn: 'root' })
export class DigitalTwinService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${environment.apiBaseUrl}/digitaltwin`;

  /**
   * organizationId dikirim manual lewat header X-Organization-Id --
   * pola sama deterioration-chart.service.ts (stub auth, engineering-rules.md
   * §8).
   */
  getViewerPayload(organizationId: string, assetId: string): Observable<ViewerPayloadDto> {
    return this.http.get<ViewerPayloadDto>(
      `${this.baseUrl}/assets/${assetId}/viewer-payload/`,
      { headers: { 'X-Organization-Id': organizationId } },
    );
  }

  /**
   * visualization.md §1: browser TIDAK mengakses SeaweedFS langsung --
   * fetch bytes .glb lewat proxy backend (apps/digitaltwin/api.py
   * download_digital_twin_model), org-scoped. responseType 'arraybuffer'
   * karena ini binary (GLTFLoader.parse() butuh ArrayBuffer, bukan JSON).
   */
  downloadModelBytes(organizationId: string, modelId: string): Observable<ArrayBuffer> {
    return this.http.get(`${this.baseUrl}/models/${modelId}/download/`, {
      headers: { 'X-Organization-Id': organizationId },
      responseType: 'arraybuffer',
    });
  }

  getMaintenanceMarkers(organizationId: string, assetId: string): Observable<MaintenanceMarkerDto[]> {
    return this.http.get<MaintenanceMarkerDto[]>(
      `${this.baseUrl}/assets/${assetId}/maintenance-markers/`,
      { headers: { 'X-Organization-Id': organizationId } },
    );
  }

  uploadModel(
    organizationId: string,
    assetId: string,
    file: File,
    source: string,
  ): Observable<DigitalTwinUploadResponseDto> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('source', source);

    return this.http.post<DigitalTwinUploadResponseDto>(
      `${this.baseUrl}/assets/${assetId}/upload/`,
      formData,
      { headers: { 'X-Organization-Id': organizationId } },
    );
  }

  /**
   * visualization.md §6: fetch awal anomaly hotspot marker (state saat
   * viewer dibuka) -- WebSocket (connectAssetAlerts di bawah) menambah
   * marker baru SETELAH ini secara real-time, tidak menggantikan fetch
   * awal.
   */
  getAnomalyMarkers(organizationId: string, assetId: string): Observable<AnomalyMarkerDto[]> {
    return this.http.get<AnomalyMarkerDto[]>(
      `${this.baseUrl}/assets/${assetId}/anomaly-markers/`,
      { headers: { 'X-Organization-Id': organizationId } },
    );
  }

  /**
   * visualization.md §6: daftar event untuk panel detail marker (hanya
   * baca). Batas jumlah diterapkan di server (ANOMALY_PANEL_MAX_EVENTS).
   */
  getAnomalyEvents(
    organizationId: string,
    assetId: string,
    componentType: string,
  ): Observable<AnomalyEventDetailDto[]> {
    return this.http.get<AnomalyEventDetailDto[]>(
      `${this.baseUrl}/assets/${assetId}/anomaly-events/`,
      {
        headers: { 'X-Organization-Id': organizationId },
        params: { component_type: componentType },
      },
    );
  }

  /**
   * visualization.md §6: sensor trace. Endpoint-nya di app `sensors`
   * (hanya sensors/deterioration yang boleh membaca Parquet, database.md
   * §0), bukan di /digitaltwin -- karena itu tidak memakai this.baseUrl.
   * start/end: ISO 8601 UTC berzona waktu (lihat traceWindowAround).
   */
  getSensorTrace(
    organizationId: string,
    deviceId: string,
    start: string,
    end: string,
  ): Observable<SensorTraceDto> {
    return this.http.get<SensorTraceDto>(
      `${environment.apiBaseUrl}/sensors/devices/${deviceId}/readings/`,
      { headers: { 'X-Organization-Id': organizationId }, params: { start, end } },
    );
  }

  /**
   * architecture.md §5: /ws/assets/{asset_id}/alerts -- push real-time
   * SensorAnomalyDetected. WebSocket native (bukan library RxJS
   * WebSocketSubject) -- KASUS PERTAMA koneksi real-time di frontend,
   * belum ada preseden pola di project ini; native API dipilih karena
   * paling eksplisit/minim dependency untuk kasus tunggal ini (satu
   * consumer, payload JSON sederhana, tidak butuh reconnect logic
   * canggih untuk versi awal).
   *
   * BELUM ada X-Organization-Id/auth di level WebSocket (Keycloak realm
   * belum ada, konsisten stub di seluruh REST API) -- lihat
   * apps/sensors/consumers.py untuk keterbatasan yang sama persis di
   * backend.
   *
   * Caller bertanggung jawab memanggil .close() pada WebSocket yang
   * dikembalikan saat ngOnDestroy (pola sama seperti dispose() Three.js
   * scene di viewer component -- lifecycle cleanup eksplisit, bukan
   * bergantung garbage collection).
   */
  connectAssetAlerts(assetId: string): {
    socket: WebSocket;
    messages$: Observable<AssetAlertsPayload>;
  } {
    const wsProtocol = environment.apiBaseUrl.startsWith('https') ? 'wss' : 'ws';
    const wsHost = environment.apiBaseUrl.replace(/^https?:\/\//, '').replace(/\/api$/, '');
    const socket = new WebSocket(`${wsProtocol}://${wsHost}/ws/assets/${assetId}/alerts`);

    const messages$ = new Observable<AssetAlertsPayload>((subscriber) => {
      socket.onmessage = (event: MessageEvent<string>) => {
        subscriber.next(JSON.parse(event.data) as AssetAlertsPayload);
      };
      socket.onerror = (event: Event) => {
        subscriber.error(event);
      };
      socket.onclose = () => {
        subscriber.complete();
      };
    });

    return { socket, messages$ };
  }
}
