# Touch Bar Info Plugin for StreamController

Touch Bar Info is a feature-rich, full-canvas information display plugin built for StreamController on the Elgato Stream Deck +. It turns the 800x100 touch strip into a clean, customizable desktop dashboard for monitoring system performance, weather, time, and disk usage in real time.

---

## Available Widgets

### Stacked Date & Time
Displays your local date and time stacked across two lines. You can customize 12-hour or 24-hour clock formats, toggle seconds on or off, and choose from multiple date formatting styles (such as `Mon. Aug 11, 2026`, `08/11/2026`, or `11/08/2026`).

### Standalone Date
A clean, single-line date display formatted to your preference.

### Standalone Time
A high-visibility digital clock display with customizable typography, colors, and text outlines.

### Real-Time Weather
Provides live temperature, weather conditions, and location info retrieved automatically via Open-Meteo.

### CPU Monitor
Tracks live processor load percentage alongside an optional real-time utilization graph.

### RAM Usage Monitor
Monitors system memory consumption with three distinct display modes:
- **Percentage Mode**: Displays current RAM load percentage.
- **Used / Total GB Mode**: Displays a detailed breakdown of used and total system memory.
- **Live Graph Mode**: Shows a continuous real-time memory graph.

### Network Activity Monitor
Tracks live upload (TX) and download (RX) throughput. Offers toggles for KB/s or MB/s units and includes a live traffic graph.

### System Disk Usage Monitor
Monitors any physical partition or directory path (such as System Root `/`, Home `/home/user`, `/mnt/Games`, or `/mnt/Stuff`) selected using a native folder picker. Features three clean display modes:
- **Percentage Mode**: A stacked 2-line layout showing the disk name and used percentage (e.g. `Home (oscar)` / `17% Used`).
- **Used / Free GB Mode**: A stacked 2-line layout showing the disk name and exact capacity breakdown (e.g. `Games` / `337G Used / 107G Free`).
- **Live Bar Graph Mode**: A stacked layout featuring a header title on top and a sleek progress bar underneath showing available vs. used space.

---

## Key Features & Customization

- **Modular 3-Section Grid**: Divide the Touch Bar canvas into three sections (A, B, and C). Each section can host either a full-height single widget or split into dual top and bottom sub-slots.
- **Custom Background Wallpapers**: Render custom PNG or JPG wallpaper images behind all Touch Bar widgets.
- **Typography & Styling Controls**: Customize fonts, text fill colors, and outline strokes for Date, Time, and Weather widgets.
- **Multi-Input Support**: Works across Touchscreen (`sd-plus`), Dials, and Keys.

---

## Acknowledgments

This plugin and its documentation were developed with AI assistance (Google DeepMind Antigravity AI) for code architecture, performance optimization, and clear documentation.

---

<img width="415" height="75" alt="Touch Bar Info Screenshot" src="https://github.com/user-attachments/assets/c923b95c-4cd7-456f-9341-200f89dce235" />
