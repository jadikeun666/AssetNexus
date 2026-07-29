import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import { DigitalTwinUploadResponseDto, ViewerPayloadDto } from '../models/digital-twin.model';

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
}
