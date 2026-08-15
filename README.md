# TouchPulse Plugin for StreamController

TouchPulse is a modular information display plugin built for StreamController on the Elgato Stream Deck +. It is designed specifically for the device's 800x100 touch strip, allowing you to arrange and customize multiple real-time widgets across the display.

Widgets can be combined to show media playback with animated equalizers, system hardware metrics, world clocks, local weather, and date/time displays. Each section can be styled with custom fonts, colors, and background wallpapers.

> **Development Notice**: This plugin is under active development. Features and rendering options may receive updates and refinements.

---

## Touch Bar Layout and Modular Sections

The 800x100 Touch Bar canvas is divided into three customizable sections: **Section A** (Left), **Section B** (Center), and **Section C** (Right).

![Touch Bar Sections Breakdown](assets/touchbar-sections.png)

Each section can be configured in one of two ways:
- **Full Slot (Single Widget)**: Uses the entire 100px height of the section for larger displays, such as full-height media equalizers, performance graphs, or stacked date and time.
- **Split Slot (Dual Sub-slots)**: Splits the section vertically into two independent 50px Top and Bottom sub-slots, letting you stack two separate widgets (such as Date on top and Weather on bottom, or a mini media player on top and RAM monitor on bottom).

<img width="415" height="75" alt="Screenshot From 2026-08-11 20-26-51" src="https://github.com/user-attachments/assets/53001dd6-c877-4764-b15c-17b506baae2c" />
<img width="415" height="75" alt="Screenshot From 2026-08-11 20-38-17" src="https://github.com/user-attachments/assets/860ef11c-8d20-46dc-a2c9-cfc7e51c778b" />
<img width="414" height="82" alt="Screenshot From 2026-08-12 18-20-20" src="https://github.com/user-attachments/assets/ec44ed2d-4510-4ca5-9e4d-7908a511d236" />
<img width="414" height="82" alt="Screencast From 2026-08-14 12-31-26" src="https://github.com/user-attachments/assets/70673705-c0ff-4837-ab22-379f1476c7be" />

---

## Hardware Dial Controls (Stream Deck +)

TouchPulse maps the Stream Deck +'s four rotary push-encoders directly to the Touch Bar sections positioned above them:

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

### Section-by-Section Dial Mapping

#### 1. Left Section — Section A (Dial 1)
* **Full Section Mode**: Dial 1 controls the 100px widget.
* **Split Mode (Top & Bottom Sub-sections)**: Pressing/clicking Dial 1 switches active control between the **Top** and **Bottom** sub-sections.

#### 2. Center Section — Section B (Dials 2 & 3)
* **Full Section Mode**: Dials 2 and 3 operate together for the 400px widget:
  * **Dial 2 (Left)**: Primary control (e.g. track skipping).
  * **Dial 3 (Right)**: Secondary control (e.g. volume adjustment with on-screen HUD, mute/unmute).
* **Split Mode (Top & Bottom Sub-sections)**:
  * **Dial 2** controls the **Top** sub-section widget.
  * **Dial 3** controls the **Bottom** sub-section widget.

#### 3. Right Section — Section C (Dial 4)
* **Full Section Mode**: Dial 4 controls the 100px widget.
* **Split Mode (Top & Bottom Sub-sections)**: Pressing/clicking Dial 4 switches active control between the **Top** and **Bottom** sub-sections.

---

### Example Dial Actions

* **Media Player (Center Full Mode)**:
  * **Dial 2**: Turn to skip Previous / Next track; press to Play / Pause.
  * **Dial 3**: Turn to adjust Volume (brings up a temporary volume HUD on the touch bar); press to Mute / Unmute.
* **Media Player (Split Mode / Section A or C)**:
  * Control mapped to the active sub-slot via dial push toggle.
* **Weather & Clocks**:
  * Press dials to trigger a background data refresh or toggle display details.

---

### Configuration Dial Highlighting
Inside the StreamController application, expanding the configuration settings for **Section A**, **Section B**, or **Section C** highlights the corresponding physical dials on the StreamController interface, showing which hardware dials map to each section.

---

## Global Plugin Settings (Performance & Refresh Rate)

TouchPulse includes global configuration options accessible from the StreamController preferences:

* **Location**: Open **StreamController Settings** (gear icon) -> **Plugins** -> **TouchPulse** -> **Settings**.

### Options

* **Animation Refresh Rate**:
  * **18 FPS (Default & Recommended)**: Runs animations at ~55ms intervals. This provides smooth visual motion while significantly reducing USB packet volume, preventing microcontroller buffer overruns and screen tearing on the Stream Deck + LCD.
  * **30 FPS**: Runs animations at ~33ms intervals for maximum refresh rate. Recommended only if your system and USB connection handle the higher packet throughput without visual artifacts.

Changes made in the settings page take effect immediately without restarting StreamController.

---

## Available Widgets

All widgets can be placed across Sections A, B, and C in Full or Split mode:

### CPU Monitor
Shows current processor utilization percentage with an optional real-time utilization graph.

### Date
Displays the current date with customizable formats (e.g., `Mon. Aug 11, 2026`, `08/11/2026`, or `11/08/2026`).

### Disk Usage Monitor
Monitors any mount point or directory path (such as `/`, `/home/user`, or external drives). Includes three display formats:
- **Percentage Mode**: Displays partition name and percent used.
- **Used / Free GB Mode**: Displays used and free storage space in gigabytes.
- **Bar Graph Mode**: Progress bar indicating available vs. used capacity.

### Media Player
Integrates MPRIS media control directly on the touch strip:
- **MPRIS Support**: Automatically detects active players or targets specific applications (Spotify, VLC, Firefox, Chrome, etc.).
- **Album Art**: Downloads and caches track artwork.
- **Audio Visualizers**:
  - *Wave Stepped Bars*: Multi-band equalizer with simulated frequency response.
  - *Wave Curves*: Flowing sinusoidal wave rendering.
- **Adaptive Animation**: Runs the visualizer loop while media is actively playing, automatically pausing when media stops to save CPU cycles.
- **Layout Support**: Available in both Full (100px) and Split (50px) modes.
- **Styling**: Configurable bar colors, gradient fills, and typography options for track and artist labels.

### Network Activity Monitor
Monitors upload (TX) and download (RX) throughput with selectable units (KB/s or MB/s) and a live traffic graph.

### RAM Usage Monitor
Monitors system memory with three display modes:
- **Percentage Mode**: Current memory usage as a percentage.
- **Used / Total GB Mode**: Used and total memory in gigabytes.
- **Graph Mode**: Continuous real-time memory usage graph.

### Stacked Date & Time (Full Section Mode)
Displays date and time stacked across two lines with support for 12-hour/24-hour clocks, optional seconds, and multiple date formats.

### Time
Digital clock display with custom font selection, color fills, and text stroke outlines.

### Weather
Displays local temperature, weather conditions, and location using the Open-Meteo API with configurable refresh rates and temperature units (Celsius/Fahrenheit).

### World Clock
Displays real-time clocks for multiple timezones:
- **Digital & Analog Views**: Choice between text digital display or a circular analog clock face with animated hands.
- **Seconds Toggle**: Toggle seconds independently from the primary local clock.
- **Preset & Custom Timezones**: Select from standard city presets or enter any standard IANA timezone identifier (e.g. `America/New_York`, `Asia/Tokyo`).
- **Time Offset**: Shows the time difference relative to your local time.

---

## General Features

- **Modular Layout**: Configure up to 6 different widgets across 3 independent canvas sections.
- **Custom Wallpapers**: Set PNG or JPG background images behind widgets.
- **Typography & Color Customization**: Full font selector, custom font sizes, text colors, and outline strokes.
- **Screen Lock Detection**: Automatically blanks the touch bar display when the desktop is locked.

---

## Codebase Architecture & Developer Guide

TouchPulse is structured for modular extension:

```text
TouchPulse/
├── main.py                                  # Plugin entry point & global settings area
├── manifest.json                            # StreamController store metadata
├── locales/                                 # Localization files (en_US, de_DE)
├── assets/                                  # Widget icons & weather SVGs
└── actions/
    └── TouchBarInfoAction/
        └── TouchBarInfoAction.py            # Main action engine
            ├── SECTION 1: Base & State Storage
            ├── SECTION 2: System Discovery & Option Providers
            ├── SECTION 3: GTK4 / Libadwaita Preferences UI Builders
            ├── SECTION 4: Typography & Pango Font Resolution
            ├── SECTION 5: Canvas Drawing Engines (Clocks, Graphs, Visualizers)
            ├── SECTION 6: Dial Interception, Volume HUD & Media Controls
            └── SECTION 7: Display Update Loop & 1:1 ScreenBar UI Mirroring
```

### Adding a New Widget
1. **Register the Widget ID**: Add the widget key to `self.full_widget_options` and `self.sub_widget_options` in `init_options()` within `TouchBarInfoAction.py`.
2. **Add Settings UI**: Create a `build_<widget>_controls(slot_key)` function in `SECTION 3` and add it to `update_group_vis()`.
3. **Add Canvas Renderer**: Implement `draw_<widget>()` in `SECTION 5` and dispatch it inside `render_slot_widget()` in `SECTION 7`.

---

## Acknowledgments

This plugin and its documentation were developed with pair-programming assistance (Google DeepMind Antigravity AI) for code architecture, performance optimization, and documentation.
