# Google Maps API Setup Guide & Environment Configuration

MiniMartPro incorporates a full GPS discovery system, Places address autocompletion, draggable pin mapping, and travel routing directions. This relies on the Google Maps JavaScript API suite.

---

## 🛠️ Required Google Cloud Platform APIs

To successfully run all Geolocation and mapping features, ensure the following API services are enabled on your Google Cloud Console project:

1. **Maps JavaScript API** (Renders interactive maps, draggable pins, and visual routes)
2. **Places API** (Enables live location search autocompletion inside verification and search bars)
3. **Directions API** (Computes route vectors, driving distances, and travel times from customers to shops)
4. **Geolocation API** (Locates browser-level user proximity coordinates silently)

---

## 🔒 Setup Credentials & API Key

1. Navigate to the [Google Cloud Console](https://console.cloud.google.com/).
2. Select or create your project.
3. Go to **APIs & Services** > **Credentials**.
4. Click **Create Credentials** > **API Key**.
5. *Highly Recommended for Production*: Restrict your API key to only run on authorized HTTP Referrers (e.g. `localhost:5000/*` and your Vercel deployment URL `*.vercel.app/*`).

---

## ⚙️ Environment Variables Configuration

To load maps securely across all pages without exposing keys statically, add the `GOOGLE_MAPS_API_KEY` to your system environment variables.

### Local Development (`.env`)
Create a `.env` file in the project root (copied from `.env.example`) and add your API key:
```env
# Google Cloud APIs configuration
GOOGLE_MAPS_API_KEY=AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q
```

### Serverless Vercel Deployment
To configure maps globally on Vercel:
1. Open your project on the **Vercel Dashboard**.
2. Navigate to **Settings** > **Environment Variables**.
3. Create a new key:
   - **Key**: `GOOGLE_MAPS_API_KEY`
   - **Value**: `[Your Actual Google Cloud API Key]`
4. Click **Save** and trigger a fresh deployment!

---

## 🗺️ How the Marketplace Geocoding Works

### 1. Owner Verification Map
* **Page**: `/owner/verification`
* **Interface**: Interactive dark-mode map powered by Google Maps JS and Places library.
* **Flow**:
  1. The owner types a landmark or business address.
  2. The Places **Autocomplete** search lists matches.
  3. Selecting a match automatically drops a pin, geocodes it, and pans the camera.
  4. The owner can drag the pin manually to adjust coordinates.
  5. The form captures the exact `latitude` and `longitude` before submission.

### 2. Proximity Shop Discovery
* **Page**: `/shop_list` (Customer Landing Catalog)
* **Flow**:
  1. Captures client-side HTML5 browser Geolocation coordinates.
  2. Submits coordinates to the Proximity Log API `/api/gps/log` to build recommendation matrices.
  3. Employs client-side **Haversine formula** computations to calculate real-world distances:
     $$d = 2r \arcsin\left(\sqrt{\sin^2\left(\frac{\Delta \phi}{2}\right) + \cos(\phi_1)\cos(\phi_2)\sin^2\left(\frac{\Delta \lambda}{2}\right)}\right)$$
  4. Rearranges shop blocks to highlight nearby shops first, estimating travel times at ~40 km/h average driving speeds.

### 3. Directions & Route Navigations
* **Overlay**: Directions routing modal on Customer and Owner profile pages.
* **Flow**:
  1. The user clicks "Navigate" or "Route Test".
  2. Google Maps **DirectionsService** queries the optimal route from current location coordinates to the shop's pinned geocodes.
  3. Paves a gorgeous glowing neon route line over a dark theme base map via **DirectionsRenderer**.
  4. Presents exact driving distance and estimated time of arrival inside a premium HUD overlay.
