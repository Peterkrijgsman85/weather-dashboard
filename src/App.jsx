import { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";

// Fix Leaflet marker icons in Vite
import markerIcon from "leaflet/dist/images/marker-icon.png";
import markerIconRetina from "leaflet/dist/images/marker-icon-2x.png";
import markerShadow from "leaflet/dist/images/marker-shadow.png";

L.Icon.Default.mergeOptions({
  iconUrl: markerIcon,
  iconRetinaUrl: markerIconRetina,
  shadowUrl: markerShadow,
});

const DATA_URL = "/data/icon-d2/manifest.json";

function formatTime(iso) {
  return new Intl.DateTimeFormat("nl-NL", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

function formatDate(iso) {
  return new Intl.DateTimeFormat("nl-NL", {
    weekday: "short",
    day: "numeric",
    month: "short",
  }).format(new Date(iso));
}

function App() {
  const mapRef = useRef(null);
  const mapContainerRef = useRef(null);
  const overlayRef = useRef(null);

  const [manifest, setManifest] = useState(null);
  const [timeIndex, setTimeIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(true);

  /*
   * Load model metadata.
   */
  useEffect(() => {
    fetch(DATA_URL)
      .then((response) => {
        if (!response.ok) {
          throw new Error("Manifest kon niet worden geladen.");
        }

        return response.json();
      })
      .then((data) => {
        setManifest(data);
        setLoading(false);
      })
      .catch((error) => {
        console.error(error);
        setLoading(false);
      });
  }, []);

  /*
   * Initialize map.
   */
  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) {
      return;
    }

    const map = L.map(mapContainerRef.current, {
      zoomControl: false,
      attributionControl: true,
    });

    L.control.zoom({
      position: "bottomright",
    }).addTo(map);

    L.tileLayer(
      "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
      {
        maxZoom: 18,
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      }
    ).addTo(map);

    map.fitBounds([
      [50.5, 3.0],
      [54.0, 8.0],
    ]);

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  /*
   * Update weather overlay.
   */
  useEffect(() => {
    if (!manifest || !mapRef.current) {
      return;
    }

    const frame = manifest.frames[timeIndex];

    if (!frame) {
      return;
    }

    if (overlayRef.current) {
      overlayRef.current.remove();
    }

    overlayRef.current = L.imageOverlay(
      frame.image,
      manifest.bounds,
      {
        opacity: 0.78,
        interactive: false,
      }
    ).addTo(mapRef.current);
  }, [manifest, timeIndex]);

  /*
   * Playback.
   */
  useEffect(() => {
    if (!playing || !manifest) {
      return;
    }

    const timer = setInterval(() => {
      setTimeIndex((current) => {
        if (current >= manifest.frames.length - 1) {
          setPlaying(false);
          return current;
        }

        return current + 1;
      });
    }, 500);

    return () => clearInterval(timer);
  }, [playing, manifest]);

  const currentFrame = useMemo(() => {
    return manifest?.frames?.[timeIndex];
  }, [manifest, timeIndex]);

  if (loading) {
    return (
      <div className="loading">
        <div className="loading-title">ICON-D2</div>
        <div className="loading-subtitle">
          modeldata laden...
        </div>
      </div>
    );
  }

  if (!manifest) {
    return (
      <div className="loading">
        <div className="loading-title">Geen modeldata</div>
        <div className="loading-subtitle">
          Er is nog geen ICON-D2 dataset gepubliceerd.
        </div>
      </div>
    );
  }

  return (
    <main className="app">

      <header className="topbar">

        <div>
          <div className="eyebrow">
            NUMERICAL WEATHER MODEL
          </div>

          <h1>ICON-D2</h1>
        </div>

        <div className="run-info">
          <div className="run-label">
            MODEL RUN
          </div>

          <div className="run-value">
            {manifest.run}
          </div>
        </div>

      </header>

      <section className="map-wrapper">

        <div
          ref={mapContainerRef}
          className="map"
        />

        <div className="map-status">

          <div className="status-model">
            ICON-D2
          </div>

          <div className="status-divider" />

          <div>
            {currentFrame
              ? formatDate(currentFrame.validTime)
              : ""}
          </div>

          <div>
            {currentFrame
              ? formatTime(currentFrame.validTime)
              : ""}
          </div>

        </div>

        <div className="legend">

          <div className="legend-title">
            TEMPERATURE · °C
          </div>

          <div className="legend-gradient" />

          <div className="legend-values">
            <span>-5</span>
            <span>0</span>
            <span>5</span>
            <span>10</span>
            <span>15</span>
            <span>20</span>
            <span>25</span>
            <span>30</span>
          </div>

        </div>

      </section>

      <section className="controls">

        <div className="layer-row">

          <div className="section-label">
            LAYER
          </div>

          <button className="layer active">
            Temperature
          </button>

          <button className="layer disabled">
            Neerslag
          </button>

          <button className="layer disabled">
            Wind
          </button>

          <button className="layer disabled">
            CAPE
          </button>

          <div className="coming-soon">
            meer lagen volgen
          </div>

        </div>

        <div className="timeline">

          <button
            className="play"
            onClick={() => {
              if (
                timeIndex >=
                manifest.frames.length - 1
              ) {
                setTimeIndex(0);
              }

              setPlaying((value) => !value);
            }}
          >
            {playing ? "Ⅱ" : "▶"}
          </button>

          <div className="timeline-content">

            <input
              type="range"
              min="0"
              max={manifest.frames.length - 1}
              value={timeIndex}
              onChange={(event) => {
                setPlaying(false);
                setTimeIndex(
                  Number(event.target.value)
                );
              }}
            />

            <div className="timeline-labels">

              {manifest.frames.map((frame, index) => (
                <span key={frame.validTime}>
                  {index % 3 === 0
                    ? formatTime(frame.validTime)
                    : ""}
                </span>
              ))}

            </div>

          </div>

          <div className="current-time">

            <div className="current-date">
              {currentFrame
                ? formatDate(currentFrame.validTime)
                : ""}
            </div>

            <div className="current-hour">
              {currentFrame
                ? formatTime(currentFrame.validTime)
                : ""}
            </div>

          </div>

        </div>

      </section>

      <footer>

        <div>
          ICON-D2 · {manifest.resolution}
        </div>

        <div>
          Data: DWD Open Data
        </div>

      </footer>

    </main>
  );
}

export default App;
