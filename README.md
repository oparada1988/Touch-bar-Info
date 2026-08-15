# TouchPulse Plugin for StreamController

TouchPulse is a highly customizable, full-canvas information display plugin built for StreamController on the Elgato Stream Deck +. It unlocks the full potential of your device's 800x100 touch strip, giving you complete freedom to mix, match, and arrange a wide variety of real-time widgets to make your Touch Bar truly unique to your daily workflow.

Whether you want an ultra-clean live music visualizer, an informative system performance monitor, global timezones, live weather updates, or a sleek stacked clock, TouchPulse lets you tailor every pixel with custom typography, gradients, colors, and background wallpapers.

> **Development Notice**: This plugin is currently under active development. Features, user controls, and rendering options are subject to ongoing updates and refinements.

---

## Touch Bar Layout & Modular Sections

The 800x100 Touch Bar canvas is divided into three customizable modular sections: **Section A** (Left), **Section B** (Center), and **Section C** (Right).

![Touch Bar Sections Breakdown](assets/touchbar-sections.png)

You have the flexibility to configure each section independently:
- **Full Slot (Single Widget)**: Spans the full 100px height of the section for bold, detailed displays (such as full-height media equalizers, performance graphs, or stacked date and time).
- **Split Slot (Dual Sub-slots)**: Splits the section vertically into two independent 50px Top and Bottom sub-slots, letting you stack any two widgets together (such as Date on top and Weather on bottom, or a compact Media mini-player on top and RAM on bottom).

<img width="415" height="75" alt="Screenshot From 2026-08-11 20-26-51" src="https://github.com/user-attachments/assets/53001dd6-c877-4764-b15c-17b506baae2c" />
<img width="415" height="75" alt="Screenshot From 2026-08-11 20-38-17" src="https://github.com/user-attachments/assets/860ef11c-8d20-46dc-a2c9-cfc7e51c778b" />
<img width="414" height="82" alt="Screenshot From 2026-08-12 18-20-20" src="https://github.com/user-attachments/assets/ec44ed2d-4510-4ca5-9e4d-7908a511d236" />
<img width="414" height="82" alt="Screencast From 2026-08-14 12-31-26" src="https://github.com/user-attachments/assets/70673705-c0ff-4837-ab22-379f1476c7be" />

---

## Universal Hardware Dial Controls (Stream Deck +)

TouchPulse features a universal, hardware-aligned dial control architecture designed to intuitively map the Stream Deck +'s four rotary push-encoders directly to the Touch Bar canvas positioned above them:

```
 ┌───────────────────┬───────────────────────────────────────┬───────────────────┐
 │   Section A       │               Section B               │   Section C       │
 │   (Left - 200px)  │            (Center - 400px)           │   (Right - 200px) │
 └─────────┬─────────┴───────────┬───────────────┬───────────┴─────────┬─────────┘
           │                     │               │                     │
       ┌───┴───┐             ┌───┴───┐       ┌───┴───┐             ┌───┴───┐
       │Dial #1│             │Dial #2│       │Dial #3│             │Dial #4│
       └───────┘             └───────┘       └───────┘             └───────┘
```

### 🎛️ Section-by-Section Universal Dial Architecture

#### 1. Left Section — Section A (Dial 1 / Dial #0)
* **Whole (Full Section Mode)**:
  * Dial 1 functions as a single unified controller dedicated to the full 100px widget.
* **Split Mode (Top & Bottom Sub-sections)**:
  * **Click to Toggle Sub-section**: Pushing/clicking Dial 1 switches active control between the **Top** and **Bottom** sub-sections, allowing effortless single-dial interaction across stacked widgets.

#### 2. Center Section — Section B (Dials 2 & 3 / Dials #1 & #2)
* **Whole (Full Section Mode)**:
  * Both dials operate in tandem as a synchronized **dual-dial control pair** for the wide 400px widget:
    * **Left Dial (Dial 2)**: Primary navigation / selection (e.g. track skipping, scrolling).
    * **Right Dial (Dial 3)**: Secondary control / adjustment (e.g. volume adjustment, action toggles).
* **Split Mode (Top & Bottom Sub-sections)**:
  * Dedicated 1-to-1 hardware mapping:
    * **Left Dial (Dial 2)** is dedicated entirely to the **Top** sub-section widget.
    * **Right Dial (Dial 3)** is dedicated entirely to the **Bottom** sub-section widget.

#### 3. Right Section — Section C (Dial 4 / Dial #3)
* **Whole (Full Section Mode)**:
  * Dial 4 functions as a single unified controller dedicated to the full 100px widget.
* **Split Mode (Top & Bottom Sub-sections)**:
  * **Click to Toggle Sub-section**: Pushing/clicking Dial 4 switches active control between the **Top** and **Bottom** sub-sections.

---

### 💡 Example Widget Integrations

* **Media Player (Center Section Full Mode)**:
  * **Left Dial**: Turn to skip Previous / Next track; Click to Play / Pause.
  * **Right Dial**: Turn to adjust Volume (replaces the visualizer with an animated Volume Meter HUD for 3 seconds); Click to Mute / Unmute.
* **Media Player (Split Mode / Section A or C)**:
  * Full control mapped either to the top or bottom sub-slot with single-dial toggle or dedicated dual-slot assignment.
* **Weather & Clocks**:
  * Push dials to trigger instantaneous background data refresh or toggle display modes.

---

### 🌟 Interactive Configuration Dial Glowing
* Inside the StreamController application window, expanding the configuration settings for **Section A**, **Section B**, or **Section C** dynamically illuminates and glows the corresponding physical dials on the StreamController interface, providing instant visual feedback on which hardware knobs control each section.

---

## Available Widgets

All widgets can be placed anywhere across Sections A, B, and C in Full or Split mode and are listed in alphabetical order:

### CPU Monitor
Tracks live processor load percentage alongside an optional real-time utilization graph.

### Date
A clean, single-line date display formatted to your preference (e.g. `Mon. Aug 11, 2026`, `08/11/2026`, or `11/08/2026`).

### Disk Usage Monitor
Monitors any physical partition or custom directory path (such as System Root `/`, Home `/home/user`, `/mnt/Games`, or `/mnt/Stuff`) selected using a native folder picker. Features three clean display modes:
- **Percentage Mode**: A stacked 2-line layout showing the disk name and used percentage (e.g. `Home (oscar)` / `17% Used`).
- **Used / Free GB Mode**: A stacked 2-line layout showing the disk name and exact capacity breakdown (e.g. `Games` / `337G Used / 107G Free`).
- **Live Bar Graph Mode**: A sleek progress bar underneath the mount title showing available vs. used space.

### Media Player
Turns your Touch Bar into a live mini-player and audio equalizer:
- **Universal MPRIS Compatibility**: Automatically detects currently playing audio or lets you choose specific installed players on your system (like Spotify, VLC, Firefox, or Chrome).
- **Album Artwork Display**: Automatically fetches and caches high-res track artwork.
- **Dynamic Audio Visualizers**:
  - *Wave Stepped Bars*: A multi-band equalizer with authentic frequency dynamics (deep bass bounce, mid harmonics, and treble jitter) rendered as discrete matrix-stepped LED columns.
  - *Wave Curves*: Smooth, flowing sinusoidal wave curves.
- **Fluid 25 FPS Animation**: High frame rate animation loop that runs smoothly while music is playing and automatically pauses when media is stopped to save system resources.
- **Full & Split Slot Support**:
  - *Full Section (100px)*: High-detail view featuring album art, scrolling song title and artist typography, and the equalizer below.
  - *Split Subsection (50px)*: Compact mini-cover art and wide equalizer visualization.
- **Coloring & Typography**: Customize visualizer colors with solid colors or vibrant two-color gradients, plus full typography controls (custom fonts, text fill colors, and stroke outlines) for song and artist names.

### Network Activity Monitor
Tracks live upload (TX) and download (RX) throughput. Offers toggles for KB/s or MB/s units and includes a live traffic graph.

### RAM Usage Monitor
Monitors system memory consumption with three distinct display modes:
- **Percentage Mode**: Displays current RAM load percentage.
- **Used / Total GB Mode**: Displays a detailed breakdown of used and total system memory.
- **Live Graph Mode**: Shows a continuous real-time memory graph.

### Stacked Date & Time *(Full Section Mode)*
Displays your local date and time stacked across two lines. You can customize 12-hour or 24-hour clock formats, toggle seconds on or off, and choose from multiple date formatting styles.

### Time
A high-visibility digital clock display with customizable typography, colors, and text outlines.

### Weather
Provides live temperature, weather conditions, and location info retrieved automatically via Open-Meteo with customizable refresh intervals and units (°C/°F).

### World Clock
Displays a real-time clock for any global location with automatic time difference calculations:
- **Digital & Analog Clock Views**: Choose between a clean Digital text view or a round Analog clock face featuring animated hour, minute, and second hands.
- **Independent Seconds Toggle**: Easily toggle seconds on or off for the World Clock independently from the standalone Time widget.
- **Preset Cities**: Quick selection for major cities (London, New York, Los Angeles, Chicago, Paris, Berlin, Tokyo, Hong Kong, Sydney, Dubai, UTC).
- **Custom IANA Timezones**: Full support for any custom IANA timezone string (e.g. `America/New_York`, `Asia/Tokyo`, `Europe/Paris`) with custom city labels.
- **Time Offset & Day Indicator**: Displays time difference relative to local time along with day indicators (e.g., `+5h, Tomorrow` or `-3h`).
- **Full Typography & Styling**: Custom GTK font selector, font colors, and stroke outlines.

---

## Key Features & Personalization

- **Complete Creative Freedom**: Mix, match, and arrange up to 6 different widgets simultaneously across the 3 modular sections to design a Touch Bar tailored precisely to your desk setup.
- **Live Media Player & Visualizer**: Real-time MPRIS player integration with album art and 25 FPS audio visualizers.
- **Custom Background Wallpapers**: Set custom PNG or JPG wallpaper images behind all Touch Bar widgets.
- **Deep Typography & Color Styling**: Full font selectors, custom fill colors, and outline strokes across clock, date, weather, and media typography.
- **Power-Saving Lock Blanking**: Automatically blanks the display when your computer screen locks.
---

## 🏗️ Codebase Architecture & Developer Guide

TouchPulse is built with a clean, modular architecture designed for easy modification and extension. If you want to fork the repository or add new widgets, here is a quick overview of how the codebase is structured:

```text
TouchPulse/
├── main.py                                  # Plugin entry point & ActionHolder registration
├── manifest.json                            # StreamController store metadata & permissions
├── locales/                                 # Localization dictionaries (en_US, de_DE)
├── assets/                                  # Icons (cpu, ram, disk, net, media) & weather SVGs
└── actions/
    └── TouchBarInfoAction/
        └── TouchBarInfoAction.py            # Main action engine (~4500 lines)
            ├── SECTION 1: Base & State Storage
            ├── SECTION 2: System Discovery & Option Providers
            ├── SECTION 3: GTK4 / Libadwaita Preferences UI Builders
            ├── SECTION 4: Typography & Pango Font Resolution
            ├── SECTION 5: Canvas Drawing Engines (Clocks, Graphs, Visualizers)
            ├── SECTION 6: Dial Interception, Volume HUD & Media Controls
            └── SECTION 7: Display Update Loop & 1:1 ScreenBar UI Mirroring
```

### 💡 How to Add a New Widget in 3 Steps:
1. **Register the Widget ID**: Add your widget name to `self.full_widget_options` and `self.sub_widget_options` in `init_options()` in `TouchBarInfoAction.py`.
2. **Build Settings UI**: Add a `build_<widget>_controls(slot_key)` function in `SECTION 3` and include it in `update_group_vis()`.
3. **Add the Canvas Renderer**: Implement `draw_<widget>()` in `SECTION 5` and dispatch it inside `render_slot_widget()` in `SECTION 7`.

---

## Acknowledgments

This plugin and its documentation were developed with pair-programming assistance (Google DeepMind Antigravity AI) for code architecture, performance optimization, and clear documentation.

---
