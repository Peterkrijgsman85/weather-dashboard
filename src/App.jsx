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

const LAYER_CONFIG = {
  temperature: {
    label: "Temperatuur",
    variable: "t_2m",
    unit: "°C",
    description: "Luchttemperatuur op 2 meter hoogte",
    legendValues: ["-5", "0", "5", "10", "15", "20", "25", "30"],
  },
  dewpoint: {
    label: "Dauwpunt",
    variable: "td_2m",
    unit: "°C",
    description: "Temperatuur waarop lucht verzadigd wordt (condensatie optreedt)",
    legendValues: ["-10", "-5", "0", "5", "10", "15", "20"],
  },
  humidity: {
    label: "Luchtvochtigheid",
    variable: "rh_2m",
    unit: "%",
    description: "Relatieve luchtvochtigheid op 2 meter hoogte",
    legendValues: ["0", "20", "40", "60", "80", "100"],
  },
  wind: {
    label: "Wind",
    variable: "u_10m",
    unit: "m/s",
    description: "Windsnelheid op 10 meter hoogte (oost-west component)",
    legendValues: ["0", "5", "10", "15", "25"],
  },
  wind_v: {
    label: "Wind (Noord-Zuid)",
    variable: "v_10m",
    unit: "m/s",
    description: "Windsnelheid op 10 meter hoogte (noord-zuid component)",
    legendValues: ["0", "5", "10", "15", "25"],
  },
  precipitation: {
    label: "Neerslag",
    variable: "tot_prec",
    unit: "mm",
    description: "Totale verwachte neerslag (regen + sneeuw) in volgende uur",
    legendValues: ["0", "1", "5", "10", "20"],
  },
  clouds: {
    label: "Bewolking",
    variable: "clct",
    unit: "%",
    description: "Percentage wolkenbedekkking van de lucht",
    legendValues: ["0", "20", "40", "60", "80", "100"],
  },
};

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
  const [activeLayer, setActiveLayer] = useState("temperature");

  /*
   * Load model metadata.
   */
  useEffect(() => {
    console.log("Fetching manifest from:", DATA_URL);
    fetch(DATA_URL)
      .then((response) => {
        console.log("Manifest response:", response.status);
        if (!response.ok) {
          throw new Error("Manifest kon niet worden geladen.");
        }

        return response.json();
      })
      .then((data) => {
        console.log("Manifest loaded:", data);
        setManifest(data);
        setLoading(false);
      })
      .catch((error) => {
        console.error("Manifest error:", error);
        setLoading(false);
      });
  }, []);

  /*
   * Initialize map.
   */
  useEffect(() => {
    // Only initialize after component has rendered
    if (!mapContainerRef.current || mapRef.current) {
      return;
    }

    console.log("Starting map initialization");

    const container = mapContainerRef.current;
    
    console.log("Map container dimensions:", {
      width: container.offsetWidth,
      height: container.offsetHeight,
    });

    try {
      const map = L.map(container, {
        zoomControl: false,
        attributionControl: true,
      });

      console.log("Map created successfully");

      L.control.zoom({
        position: "bottomright",
      }).addTo(map);

      // Use OpenTopoMap as base layer (no API key needed, dark theme good for overlays)
      L.tileLayer(
        "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
        {
          maxZoom: 17,
          attribution:
            'Map data: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, <a href="http://viewfinderpanoramas.org">SRTM</a> | Map style: &copy; <a href="https://opentopomap.org">OpenTopoMap</a>',
        }
      ).addTo(map);

      // Fit map to data bounds with padding (Netherlands region)
      // Bounds: lat 50.5-54.0, lon 2.5-8.5 (data region)
      const dataBounds = [
        [50.3, 2.2],  // SW corner with padding
        [54.2, 8.8],  // NE corner with padding
      ];
      map.fitBounds(dataBounds, { padding: [50, 50] });

      mapRef.current = map;
      console.log("Map initialized and stored in ref");
    } catch (error) {
      console.error("Error initializing map:", error);
    }

    return () => {
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
    };
  }, [manifest]);

  /*
   * Get current frames for active layer
   */
  const currentLayerFrames = useMemo(() => {
    if (!manifest || !activeLayer) {
      return [];
    }

    const config = LAYER_CONFIG[activeLayer];
    if (!config) return [];

    const variable = config.variable;
    return manifest.variables?.[variable]?.frames || [];
  }, [manifest, activeLayer]);

  /*
   * Reset timeIndex when layer changes
   */
  useEffect(() => {
    setTimeIndex(0);
  }, [activeLayer]);

  /*
   * Update weather overlay.
   */
  useEffect(() => {
    if (!manifest || !mapRef.current || currentLayerFrames.length === 0) {
      return;
    }

    const frame = currentLayerFrames[timeIndex];

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
  }, [manifest, timeIndex, currentLayerFrames]);

  /*
   * Playback.
   */
  useEffect(() => {
    if (!playing || currentLayerFrames.length === 0) {
      return;
    }

    const timer = setInterval(() => {
      setTimeIndex((current) => {
        if (current >= currentLayerFrames.length - 1) {
          setPlaying(false);
          return current;
        }

        return current + 1;
      });
    }, 500);

    return () => clearInterval(timer);
  }, [playing, currentLayerFrames]);

  const currentFrame = useMemo(() => {
    return currentLayerFrames?.[timeIndex];
  }, [currentLayerFrames, timeIndex]);

  const layerConfig = LAYER_CONFIG[activeLayer];

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

  if (!manifest || Object.keys(manifest.variables || {}).length === 0) {
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

      <div className="app-container">

        {/* Left Sidebar: Layer Selection */}
        <aside className="sidebar">

          <div className="sidebar-header">
            <div className="section-label">WEERKAARTEN</div>
          </div>

          <div className="layer-cards">
            {Object.entries(LAYER_CONFIG).map(([key, config]) => {
              const hasData = manifest.variables?.[config.variable];
              return (
                <button
                  key={key}
                  className={`layer-card ${activeLayer === key ? "active" : ""} ${!hasData ? "disabled" : ""}`}
                  onClick={() => hasData && setActiveLayer(key)}
                  disabled={!hasData}
                >
                  <div className="card-label">{config.label}</div>
                  <div className="card-unit">{config.unit}</div>
                  <div className="card-description">{config.description}</div>
                  {!hasData && <div className="card-status">Geen data</div>}
                </button>
              );
            })}
          </div>

        </aside>

        {/* Center: Map */}
        <div className="main-content">

          <section className="map-wrapper">

            <div
              ref={mapContainerRef}
              className="map"
            />

            <div className="map-status">

              <div className="status-model">
                {layerConfig?.label || "ICON-D2"}
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
                {layerConfig?.label || "Data"} · {layerConfig?.unit || ""}
              </div>

              <div className="legend-gradient" />

              <div className="legend-values">
                {layerConfig?.legendValues?.map((val) => (
                  <span key={val}>{val}</span>
                ))}
              </div>

            </div>

          </section>

          {/* Timeline Controls */}
          <section className="controls">

            <div className="timeline">

              <button
                className="play"
                onClick={() => {
                  if (
                    timeIndex >=
                    currentLayerFrames.length - 1
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
                  max={Math.max(0, currentLayerFrames.length - 1)}
                  value={timeIndex}
                  onChange={(event) => {
                    setPlaying(false);
                    setTimeIndex(
                      Number(event.target.value)
                    );
                  }}
                />

                <div className="timeline-labels">

                  {currentLayerFrames.map((frame, index) => (
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

        </div>

      </div>

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
