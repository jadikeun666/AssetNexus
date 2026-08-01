import {
  AfterViewInit,
  Component,
  DestroyRef,
  ElementRef,
  OnDestroy,
  ViewChild,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

import { DigitalTwinService } from '../../../core/services/digital-twin.service';
import { ComponentForecastDto } from '../../../core/models/digital-twin.model';
import {
  PLAY_MS_PER_YEAR,
  conditionScoreToColor,
  easeConditionScore,
  isCriticalState,
  lerpColor,
  pulseEmissiveIntensity,
  rgbToHex,
  SNAP_TO_GREEN_COLOR,
} from './timeline-math';
import { DIGITAL_TWIN } from './digital-twin.constants';
import { MaintenanceMarkerDto } from '../../../core/models/digital-twin.model';

// visualization.md §1: "renders in a fixed neutral gray" untuk node
// tanpa match component -- kode hex TIDAK dispesifikasikan dokumen,
// #9E9E9E (Material Design grey 500) dipilih sebagai asumsi eksplisit
// yang didokumentasikan, bukan ditebak diam-diam.
const NEUTRAL_GRAY_RGB = { r: 0x9e, g: 0x9e, b: 0x9e };

/**
 * visualization.md §2: viewer stack Three.js -- WebGLRenderer + GLTFLoader
 * + OrbitControls + lighting HemisphereLight + DirectionalLight, dibungkus
 * lifecycle ngAfterViewInit/ngOnDestroy TANPA dependency framework
 * Three-Angular khusus (pola sama Observable Plot).
 *
 * RENDER-ON-DEMAND + "BOUNDED SETTLE LOOP" (disepakati eksplisit product
 * owner): visualization.md §7 membatasi HANYA 2 rAF loop KONTINU (eased
 * color transition §4.2, pulse CS5 §3). renderer.render() TIDAK dijadikan
 * loop rAF kontinu ketiga -- dipanggil eksplisit saat ada perubahan nyata
 * (init, resize, OrbitControls interaksi). OrbitControls enableDamping
 * butuh loop BOUNDED/SELF-TERMINATING terpisah (mulai saat drag dimulai,
 * berhenti otomatis ~600ms setelah drag dilepas) -- kategori berbeda dari
 * 2 loop kontinu itu.
 *
 * MODIFIER-KEY PRECISION MODE (fitur tambahan disepakati eksplisit,
 * di luar spesifikasi visualization.md tertulis): menahan Shift mematikan
 * enableDamping sementara. CATATAN JUJUR: OrbitControls Three.js sendiri
 * secara internal memakai shiftKey sebagai modifier bawaan untuk menukar
 * ROTATE<->PAN saat klik-kiri ditahan (hardcoded di library) -- product
 * owner sudah diberi tahu opsi Alt (yang tidak bentrok) tapi memilih
 * tetap Shift walau harus menerima kompromi ini.
 *
 * GROUND-CONTACT NORMALIZATION (langkah 4c, disepakati eksplisit): model
 * glTF yang dimuat TIDAK diasumsikan pivotnya di titik kontak tanah (itu
 * bergantung tool eksternal yang mengekspornya, di luar kendali kita) --
 * sebagai gantinya, scene hasil load DIGESER (translate) supaya bounding
 * box terendahnya (Y minimum) menyentuh Y=0, dan di tengah horizontal
 * (X,Z=0). Ini normalisasi eksplisit, BUKAN modifikasi geometri asli file
 * (transform di level Object3D pembungkus, file sumber tidak diubah).
 * maxPolarAngle = PI - epsilon (bukan PI/2) supaya kamera bisa mendongak
 * dari dekat tanah untuk inspeksi pondasi/bagian bawah struktur.
 */
@Component({
  selector: 'app-digital-twin-viewer',
  standalone: true,
  templateUrl: './digital-twin-viewer.component.html',
  styleUrl: './digital-twin-viewer.component.scss',
})
export class DigitalTwinViewerComponent implements AfterViewInit, OnDestroy {
  readonly organizationId = input.required<string>();
  readonly assetId = input.required<string>();

  private readonly digitalTwinService = inject(DigitalTwinService);
  private readonly destroyRef = inject(DestroyRef);

  @ViewChild('canvasContainer', { static: true })
  private canvasContainer!: ElementRef<HTMLDivElement>;

  private renderer?: THREE.WebGLRenderer;
  private scene?: THREE.Scene;
  private camera?: THREE.PerspectiveCamera;
  private controls?: OrbitControls;
  private resizeObserver?: ResizeObserver;

  private forecastByComponent: ComponentForecastDto[] = [];
  readonly maintenanceMarkers = signal<MaintenanceMarkerDto[]>([]);

  // visualization.md §4: rentang tahun timeline scrubber DIHITUNG dari
  // data forecast yang tersedia -- TIMELINE_DEFAULT_HORIZON_YEARS
  // (config/assetnexus.py) hanya berlaku kalau TIDAK ADA konteks
  // MaintenancePlan sama sekali (belum diintegrasikan, langkah 4e-5
  // terpisah). LANGKAH 4e-1: signal ini BELUM terhubung ke drag (input)
  // event -- itu langkah 4e-2 terpisah, disepakati eksplisit product
  // owner untuk verifikasi bertahap.
  readonly minYear = signal(0);
  readonly maxYear = signal(0);
  readonly activeYear = signal(0);
  readonly isPlaying = signal(false);

  private playAnimationFrameId?: number;
  private pulseAnimationFrameId?: number;
  private pulseStartTime = 0;

  private isSettling = false;
  private settleStopTimeout?: ReturnType<typeof setTimeout>;

  private readonly handleKeyDown = (event: KeyboardEvent) => this.setPrecisionMode(event, true);
  private readonly handleKeyUp = (event: KeyboardEvent) => this.setPrecisionMode(event, false);

  ngAfterViewInit(): void {
    this.initScene();
    this.loadModelOrPlaceholder();

    this.resizeObserver = new ResizeObserver(() => this.handleResize());
    this.resizeObserver.observe(this.canvasContainer.nativeElement);

    window.addEventListener('keydown', this.handleKeyDown);
    window.addEventListener('keyup', this.handleKeyUp);

    this.pulseStartTime = performance.now();
    this.runPulseLoop();
  }

  ngOnDestroy(): void {
    this.resizeObserver?.disconnect();
    if (this.settleStopTimeout) clearTimeout(this.settleStopTimeout);
    this.isSettling = false;
    this.stopPlayback();
    if (this.pulseAnimationFrameId !== undefined) {
      cancelAnimationFrame(this.pulseAnimationFrameId);
    }
    this.controls?.dispose();
    this.renderer?.dispose();
    window.removeEventListener('keydown', this.handleKeyDown);
    window.removeEventListener('keyup', this.handleKeyUp);
  }

  private initScene(): void {
    const container = this.canvasContainer.nativeElement;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x1a1a1a);

    this.camera = new THREE.PerspectiveCamera(
      50,
      container.clientWidth / container.clientHeight,
      0.1,
      1000,
    );
    this.camera.position.set(3, 3, 5);

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setSize(container.clientWidth, container.clientHeight);
    container.appendChild(this.renderer.domElement);

    // visualization.md §2: HemisphereLight + DirectionalLight, lighting
    // engineering-visualization (bukan photoreal).
    const hemisphereLight = new THREE.HemisphereLight(0xffffff, 0x444444, 1.5);
    this.scene.add(hemisphereLight);
    const directionalLight = new THREE.DirectionalLight(0xffffff, 1.5);
    directionalLight.position.set(5, 10, 7.5);
    this.scene.add(directionalLight);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.set(0, 0, 0);
    this.controls.maxPolarAngle = Math.PI - 0.05;
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.update();

    this.controls.addEventListener('start', () => this.startSettleLoop());
    this.controls.addEventListener('end', () => this.scheduleStopSettleLoop());
  }

  /**
   * visualization.md §1: fetch viewer-payload dulu untuk tahu apakah ada
   * DigitalTwinModel terupload. Kalau ada -> download bytes .glb -> parse
   * via GLTFLoader. Kalau belum ada -> box primitif placeholder (fallback
   * langkah 4b, supaya demo tetap menampilkan sesuatu sebelum model
   * sungguhan diupload).
   */
  private loadModelOrPlaceholder(): void {
    this.digitalTwinService
      .getViewerPayload(this.organizationId(), this.assetId())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (payload) => {
          this.forecastByComponent = payload.forecast_by_component;
          this.computeYearRange();
          this.fetchMaintenanceMarkers();
          if (payload.digital_twin_model) {
            this.loadGltfModel(payload.digital_twin_model.id);
          } else {
            this.addPlaceholderBox();
            this.applyHeatmapColors(this.activeYear());
            this.render();
          }
        },
        error: () => {
          // Graceful degradation: tampilkan placeholder, bukan viewer kosong/error.
          this.addPlaceholderBox();
          this.render();
        },
      });
  }

  private fetchMaintenanceMarkers(): void {
    this.digitalTwinService
      .getMaintenanceMarkers(this.organizationId(), this.assetId())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (markers) => this.maintenanceMarkers.set(markers),
        // Graceful degradation: kalau fetch marker gagal, viewer tetap
        // berfungsi penuh TANPA wrench marker/snap-to-green -- bukan
        // fitur inti (forecast heatmap tetap jalan), jadi kegagalan di
        // sini tidak boleh menghalangi apa pun yang sudah bekerja.
        error: () => this.maintenanceMarkers.set([]),
      });
  }

  private loadGltfModel(modelId: string): void {
    this.digitalTwinService
      .downloadModelBytes(this.organizationId(), modelId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (arrayBuffer) => {
          const loader = new GLTFLoader();
          loader.parse(
            arrayBuffer,
            '',
            (gltf) => {
              this.addModelToScene(gltf.scene);
              this.applyHeatmapColors(this.activeYear());
              this.render();
            },
            (error) => {
              console.error('Gagal parse glTF, fallback ke placeholder', error);
              this.addPlaceholderBox();
              this.applyHeatmapColors(this.activeYear());
              this.render();
            },
          );
        },
        error: (error) => {
          console.error('Gagal download model glTF, fallback ke placeholder', error);
          this.addPlaceholderBox();
          this.applyHeatmapColors(this.activeYear());
          this.render();
        },
      });
  }

  /**
   * GROUND-CONTACT NORMALIZATION (lihat catatan kelas): geser scene hasil
   * load supaya bounding box terendah (Y min) menyentuh Y=0, dan di
   * tengah horizontal. controls.target dipindah ke tengah-tinggi model.
   */
  private addModelToScene(model: THREE.Object3D): void {
    if (!this.scene || !this.controls) return;

    const box = new THREE.Box3().setFromObject(model);
    const size = new THREE.Vector3();
    const center = new THREE.Vector3();
    box.getSize(size);
    box.getCenter(center);

    model.position.x -= center.x;
    model.position.z -= center.z;
    model.position.y -= box.min.y;

    this.scene.add(model);
    this.controls.target.set(0, size.y / 2, 0);
    this.controls.update();
  }

  private addPlaceholderBox(): void {
    if (!this.scene || !this.controls) return;

    const BOX_HEIGHT = 1.5;
    const boxGeometry = new THREE.BoxGeometry(1.5, BOX_HEIGHT, 1.5);
    const boxMaterial = new THREE.MeshStandardMaterial({ color: 0x2e7d32 });
    const box = new THREE.Mesh(boxGeometry, boxMaterial);
    box.position.set(0, BOX_HEIGHT / 2, 0);
    box.name = 'girder'; // placeholder join-key
    this.scene.add(box);

    this.controls.target.set(0, BOX_HEIGHT / 2, 0);
    this.controls.update();
  }

  /**
   * visualization.md §3: material color per sub-mesh di-drive oleh
   * condition_score, join key = nama node PERSIS sama dengan
   * component_type (visualization.md §1). Node tanpa match -> abu-abu
   * netral, dikecualikan dari heatmap.
   */
  private applyHeatmapColors(year: number): void {
    if (!this.scene) return;

    this.scene.traverse((object) => {
      if (!(object instanceof THREE.Mesh)) return;
      const material = object.material;
      if (!(material instanceof THREE.MeshStandardMaterial)) return;

      const forecastEntry = this.forecastByComponent.find(
        (entry) => entry.component_type === object.name,
      );
      const score = forecastEntry?.year_scores[String(year)];

      if (score === undefined) {
        material.color.set(rgbToHex(NEUTRAL_GRAY_RGB));
        return;
      }
      material.color.set(rgbToHex(conditionScoreToColor(score)));
    });
  }

  private computeYearRange(): void {
    const years = this.forecastByComponent.flatMap((entry) =>
      Object.keys(entry.year_scores).map(Number),
    );
    const min = years.length > 0 ? Math.min(...years) : 0;
    const max = years.length > 0 ? Math.max(...years) : 0;
    this.minYear.set(min);
    this.maxYear.set(max);
    this.activeYear.set(min);
  }

  /**
   * visualization.md §4.2: "Dragging the scrubber updates every sub-mesh's
   * color per §3, instantly (no easing on drag -- must feel directly
   * responsive)." -- dipanggil dari (input) event <input type="range">
   * (native event, fired terus-menerus SELAMA drag, bukan cuma saat
   * dilepas) -- TIDAK ada requestAnimationFrame/interpolasi di sini,
   * murni snap instan ke tahun yang di-drag.
   */
  onScrubberInput(event: Event): void {
    const year = Number((event.target as HTMLInputElement).value);
    this.activeYear.set(year);
    this.applyHeatmapColors(year);
    this.render();
  }

  /**
   * visualization.md §4.2: "Pressing Play animates automatically from the
   * current year to the horizon end... with color eased between
   * consecutive years' condition_score (linear interpolation over the
   * 800ms window)". Ini loop rAF KONTINU #1 dari 2 yang diizinkan
   * visualization.md §7 -- berhenti OTOMATIS saat mencapai maxYear, atau
   * manual via tombol Stop.
   */
  togglePlayback(): void {
    if (this.isPlaying()) {
      this.stopPlayback();
    } else {
      this.startPlayback();
    }
  }

  private startPlayback(): void {
    if (this.activeYear() >= this.maxYear()) {
      this.activeYear.set(this.minYear());
    }
    this.isPlaying.set(true);
    this.playNextYearTransition();
  }

  private stopPlayback(): void {
    this.isPlaying.set(false);
    if (this.playAnimationFrameId !== undefined) {
      cancelAnimationFrame(this.playAnimationFrameId);
      this.playAnimationFrameId = undefined;
    }
  }

  private playNextYearTransition(): void {
    const fromYear = this.activeYear();
    const toYear = fromYear + 1;

    if (!this.isPlaying() || toYear > this.maxYear()) {
      this.stopPlayback();
      return;
    }

    const startTime = performance.now();
    const fromScores = this.snapshotScores(fromYear);
    const toScores = this.snapshotScores(toYear);

    // visualization.md §4.2: component_type yang punya intervensi
    // terjadwal PERSIS di toYear -- transisinya SNAP-TO-GREEN 150ms
    // non-eased, BUKAN eased 800ms biasa seperti component_type lain.
    const snappingComponentTypes = new Set(
      this.maintenanceMarkers()
        .filter((marker) => marker.scheduled_year === toYear)
        .map((marker) => marker.component_type),
    );
    const snapStartColors = new Map<string, ReturnType<typeof conditionScoreToColor>>();
    for (const componentType of snappingComponentTypes) {
      const startScore = fromScores.get(componentType);
      snapStartColors.set(
        componentType,
        startScore !== undefined ? conditionScoreToColor(startScore) : NEUTRAL_GRAY_RGB,
      );
    }

    const stepEasing = (now: number) => {
      if (!this.isPlaying()) return;

      const elapsed = now - startTime;
      const t = Math.min(1, elapsed / PLAY_MS_PER_YEAR);
      const snapT = Math.min(1, elapsed / DIGITAL_TWIN.INTERVENTION_SNAP_MS);
      this.applyEasedHeatmapColors(
        fromScores, toScores, t, snappingComponentTypes, snapStartColors, snapT,
      );
      this.render();

      if (t < 1) {
        this.playAnimationFrameId = requestAnimationFrame(stepEasing);
      } else {
        this.activeYear.set(toYear);
        this.playNextYearTransition();
      }
    };

    this.playAnimationFrameId = requestAnimationFrame(stepEasing);
  }

  /** Snapshot condition_score tiap component_type untuk satu tahun --
   * dipakai sebagai titik awal/akhir interpolasi easing. */
  private snapshotScores(year: number): Map<string, number | undefined> {
    const map = new Map<string, number | undefined>();
    for (const entry of this.forecastByComponent) {
      map.set(entry.component_type, entry.year_scores[String(year)]);
    }
    return map;
  }

  private applyEasedHeatmapColors(
    fromScores: Map<string, number | undefined>,
    toScores: Map<string, number | undefined>,
    t: number,
    snappingComponentTypes: Set<string>,
    snapStartColors: Map<string, ReturnType<typeof conditionScoreToColor>>,
    snapT: number,
  ): void {
    if (!this.scene) return;

    this.scene.traverse((object) => {
      if (!(object instanceof THREE.Mesh)) return;
      const material = object.material;
      if (!(material instanceof THREE.MeshStandardMaterial)) return;

      // visualization.md §4.2: component dengan intervensi terjadwal di
      // toYear ini -- SNAP 150ms non-eased ke hijau literal, BUKAN eased
      // 800ms mengikuti skor forecast biasa. Begitu snapT mencapai 1
      // (150ms berlalu), warna TETAP hijau solid sampai akhir window
      // 800ms (representasi visual "intervensi sudah terjadi").
      if (snappingComponentTypes.has(object.name)) {
        const startColor = snapStartColors.get(object.name) ?? NEUTRAL_GRAY_RGB;
        material.color.set(rgbToHex(lerpColor(startColor, SNAP_TO_GREEN_COLOR, snapT)));
        return;
      }

      const fromScore = fromScores.get(object.name);
      const toScore = toScores.get(object.name);

      if (fromScore === undefined || toScore === undefined) {
        material.color.set(rgbToHex(NEUTRAL_GRAY_RGB));
        return;
      }

      const easedScore = easeConditionScore(fromScore, toScore, t);
      material.color.set(rgbToHex(conditionScoreToColor(easedScore)));
    });
  }

  /**
   * visualization.md §3: "A component at CS5 additionally gets a subtle
   * pulsing emissive glow... via a requestAnimationFrame loop -- the one
   * deliberate 'flair' animation... reserved specifically for the
   * critical state". Ini loop rAF KONTINU #2 dari 2 yang diizinkan
   * visualization.md §7 -- jalan SEPANJANG hidup komponen (beda dari
   * settle loop OrbitControls yang bounded/self-terminating), TAPI hanya
   * benar-benar men-trigger render() kalau ADA sub-mesh berstatus CS5 di
   * scene saat ini -- kalau tidak ada komponen kritis, loop tetap
   * jalan (memenuhi kontrak "loop kontinu") tapi tidak melakukan apa pun
   * yang mahal (tidak ada render() dipanggil), konsisten semangat
   * render-on-demand.
   */
  private runPulseLoop = (): void => {
    const hadCritical = this.applyPulseToCriticalComponents();
    if (hadCritical) {
      this.render();
    }
    this.pulseAnimationFrameId = requestAnimationFrame(this.runPulseLoop);
  };

  /** Return true kalau ada minimal 1 sub-mesh CS5 yang diberi pulse. */
  private applyPulseToCriticalComponents(): boolean {
    if (!this.scene) return false;

    const elapsedMs = performance.now() - this.pulseStartTime;
    const intensity = pulseEmissiveIntensity(
      elapsedMs,
      DIGITAL_TWIN.CS5_PULSE_PERIOD_MS,
      DIGITAL_TWIN.CS5_PULSE_EMISSIVE_MIN,
      DIGITAL_TWIN.CS5_PULSE_EMISSIVE_MAX,
    );

    let hadCritical = false;
    const currentYear = this.activeYear();

    this.scene.traverse((object) => {
      if (!(object instanceof THREE.Mesh)) return;
      const material = object.material;
      if (!(material instanceof THREE.MeshStandardMaterial)) return;

      const forecastEntry = this.forecastByComponent.find(
        (entry) => entry.component_type === object.name,
      );
      const score = forecastEntry?.year_scores[String(currentYear)];

      if (score === undefined || !isCriticalState(score)) {
        material.emissiveIntensity = 0;
        return;
      }

      hadCritical = true;
      material.emissive.set('#c62828'); // visualization.md §3: warna CS5
      material.emissiveIntensity = intensity;
    });

    return hadCritical;
  }

  /** Modifier-key precision mode: Shift ditahan = damping mati (instan). */
  private setPrecisionMode(event: KeyboardEvent, active: boolean): void {
    if (event.key !== 'Shift' || !this.controls) return;
    this.controls.enableDamping = !active;
  }

  private handleResize(): void {
    const container = this.canvasContainer.nativeElement;
    if (!this.renderer || !this.camera || container.clientWidth === 0) return;

    this.camera.aspect = container.clientWidth / container.clientHeight;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(container.clientWidth, container.clientHeight);
    this.render();
  }

  private startSettleLoop(): void {
    if (this.settleStopTimeout) {
      clearTimeout(this.settleStopTimeout);
      this.settleStopTimeout = undefined;
    }
    if (this.isSettling) return;
    this.isSettling = true;
    this.runSettleLoop();
  }

  private scheduleStopSettleLoop(): void {
    this.settleStopTimeout = setTimeout(() => {
      this.isSettling = false;
    }, 600);
  }

  private runSettleLoop = (): void => {
    if (!this.isSettling) return;
    this.controls?.update();
    this.render();
    requestAnimationFrame(this.runSettleLoop);
  };

  /** Render-on-demand: satu-satunya titik panggil renderer.render(). */
  private render(): void {
    if (this.renderer && this.scene && this.camera) {
      this.renderer.render(this.scene, this.camera);
    }
  }
}
