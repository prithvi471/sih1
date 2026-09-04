# MineIQ Visual Design System Specification: Precision Intelligence

> Derived directly from the Stitch Project **"MineIQ Document Intelligence Platform"** (`projects/3926232776723368690`).
> This design system delivers a high-velocity, high-density enterprise command console engineered for statutory coal and natural resource management, geological survey leads, and ministry leadership. It replaces bureaucratic clutter with crisp typography, high-density data views, intentional whitespace (24px–32px rhythms), and bold focal metrics.

---

## 1. Color Palette

The color system operates on an asymmetric contrast model: a luminous, paper-like low-glare canvas punctuated by deep electric indigo operational cores and deep obsidian command consoles.

### 1.1 Canvas & Surfaces (Light Ground)
* **Base Canvas (`background` / `surface`)**: `#FCF8FB` (Alternative flat ground: `#FAFAFA`)
* **Elevated Card Surface (`surface-container-lowest`)**: `#FFFFFF` (pure white, isolated to cards, tables, document viewports)
* **Subtle Secondary Container (`surface-container-low`)**: `#F6F2F5`
* **Standard Container (`surface-container`)**: `#F0EDF0`
* **High Contrast Container (`surface-container-high`)**: `#EAE7EA`
* **Highest Container (`surface-container-highest`)**: `#E5E1E4`
* **Surface Dim (`surface-dim`)**: `#DCD9DC`
* **Surface Bright (`surface-bright`)**: `#FCF8FB`

### 1.2 Command Slate & Dark Void Moments (Hero / Terminal / Login)
* **Deep Obsidian Ground**: `#0B0F19` to `#1E1B4B` (used for login backdrop, code/terminal drawers, and deep document visualizers)
* **Command Console Surface**: `#0F172A` / `#09090B`
* **Dark Border / Hairline**: `rgba(255, 255, 255, 0.10)`
* **Dark Inset Gradient**: `linear-gradient(180deg, rgba(255, 255, 255, 0.12) 0%, rgba(255, 255, 255, 0.02) 100%)`

### 1.3 Primary & Interactive Indigos
* **Primary Core (`primary`)**: `#3525CD` / `#4F46E5` (used for confirmed states, system-critical actionables, selected tab indicators)
* **Primary Container (`primary-container`)**: `#4F46E5`
* **On Primary (`on-primary`)**: `#FFFFFF`
* **On Primary Container (`on-primary-container`)**: `#DAD7FF`
* **Electric Indigo Accent (`secondary-container` / accent)**: `#6063EE` / `#6366F1` (active hover states, live telemetry indicators, AI synthesis callouts)
* **Primary Fixed Dim (`primary-fixed-dim`)**: `#C3C0FF`
* **Surface Tint (`surface-tint`)**: `#4D44E3`

### 1.4 Text & Typography Colors
* **Primary Text (`on-surface` / `on-background`)**: `#1C1B1D` (Dark Charcoal / Slate)
* **Secondary / Muted Text (`on-surface-variant`)**: `#464555`
* **Tertiary / Subdued Label Text**: `#777587` / `#71717A`
* **Inverse Surface Text (`inverse-on-surface`)**: `#F3F0F2`

### 1.5 Semantic & Operational Statuses
Always accompany status colors with an approved semantic icon or explicit textual badge:
* **Telemetry Success / Validated**:
  * Text & Border: `#10B981` (Emerald)
  * Background: `#DCFCE7` (10% tint: `rgba(16, 185, 129, 0.10)`)
* **Warning / Starred Inquiry / Anomaly**:
  * Text & Border: `#F59E0B` (Amber / Gold)
  * Background: `#FEF3C7` (10% tint: `rgba(245, 158, 11, 0.10)`)
* **Critical Hazard / Discrepancy / Mismatch**:
  * Text & Border: `#EF4444` / `#BA1A1A` (Crimson)
  * Background: `#FFDAD6` / `#FEE2E2` (10% tint: `rgba(239, 68, 68, 0.10)`)
* **AI Stream / Extraction / Processing**:
  * Text & Border: `#8B5CF6` / `#6366F1` (Violet-Indigo)
  * Background: `rgba(79, 70, 229, 0.08)`

---

## 2. Typography

The platform utilizes a dual-font strategy: **Inter** for narrative and operational readability, paired with **JetBrains Mono** for all coordinates, figures, hashes, and compliance identifiers.

* **UI & Operational Sans-Serif**: `Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`
* **Technical & Data Monospace**: `"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace`

### 2.1 Scale, Sizes, Weights, and Line Heights

| Style Token | Font Family | Size | Weight | Line Height | Letter Spacing | Primary Use Case |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`display-hero`** | Inter | 56px (`3.5rem`) | 600 (SemiBold) | 64px (`4rem`) | `-0.04em` | Hero landing numbers, major KPI metrics |
| **`display-hero-mobile`**| Inter | 36px (`2.25rem`) | 600 (SemiBold) | 44px (`2.75rem`) | `-0.03em` | Mobile hero metrics |
| **`headline-lg`** | Inter | 32px (`2rem`) | 600 (SemiBold) | 38px (`2.375rem`)| `-0.03em` | Primary section headers (e.g. Document Operations) |
| **`headline-lg-mobile`**| Inter | 24px (`1.5rem`) | 600 (SemiBold) | 30px (`1.875rem`)| `-0.02em` | Mobile primary section headers |
| **`headline-md`** | Inter | 20px (`1.25rem`)| 600 (SemiBold) | 26px (`1.625rem`)| `-0.02em` | Card titles, modal headers, master item headers |
| **`headline-sm`** | Inter | 16px (`1rem`) | 600 (SemiBold) | 22px (`1.375rem`)| `-0.01em` | Grouping subheads, drawer titles |
| **`body-lg`** | Inter | 16px (`1rem`) | 400 (Regular) | 24px (`1.5rem`) | `-0.01em` | AI executive reports, formal inquiry question text |
| **`body-md`** | Inter | 14px (`0.875rem`)| 400 (Regular) | 20px (`1.25rem`)| `-0.005em` | General table text, form labels, feed descriptions |
| **`body-sm`** | Inter | 13px (`0.8125rem`)| 400 (Regular)| 18px (`1.125rem`)| `0em` | Metadata timestamps, table subtext, helper notes |
| **`label-ui`** | Inter | 12px (`0.75rem`)| 500 (Medium) | 16px (`1rem`) | `+0.01em` | Form field labels, button micro-labels, tabs |
| **`label-mono-md`** | JetBrains Mono | 12px (`0.75rem`)| 500 (Medium) | 16px (`1rem`) | `+0.02em` | Table numeric cells, percentage variances |
| **`label-mono-sm`** | JetBrains Mono | 11px (`0.6875rem`)| 500 (Medium) | 14px (`0.875rem`)| `+0.04em` | Column headers (uppercase), tags, hashes, chips |

### 2.2 Numerical & Monospace Rules
* All numeric fields (metric tons, caloric values, ash percentages, coordinates, currency exposure) must enforce:
  ```css
  font-variant-numeric: tabular-nums;
  font-family: 'JetBrains Mono', monospace;
  ```
* All cryptographic hashes (e.g. SHA-256 `0x8f2c91a...`) and timestamps must be displayed in `label-mono-sm`.

---

## 3. Spacing Scale

Built on a 4px mathematical baseline. Density is treated as a premium operational utility.

* **`space-2xs`**: `0.125rem` (2px)
* **`space-xs`**: `0.25rem` (4px)
* **`space-sm`**: `0.5rem` (8px)
* **`space-md`**: `0.75rem` (12px)
* **`space-base`**: `1rem` (16px)
* **`space-lg`**: `1.5rem` (24px)
* **`space-xl`**: `2rem` (32px)
* **`space-2xl`**: `3rem` (48px)
* **`space-3xl`**: `4rem` (64px)

### Layout Gutters & Padding
* **Desktop Grid Gutter**: `24px` (`1.5rem`)
* **Desktop Outer Margin**: `32px` (`2rem`)
* **Card Internal Padding**: `20px` to `24px` (`1.25rem` – `1.5rem`)
* **Card Gap (Feed / List)**: `16px` to `24px` (`1rem` – `1.5rem`)

---

## 4. Border Radius

Conveys architectural rigor and industrial dependability:

* **`rounded-xs` / `rounded-sm` (`4px` / `0.25rem`)**: Interactive controls — buttons, inputs, dropdown selectors, tabs, table rows.
* **`rounded-md` / `rounded-lg` (`8px` / `0.5rem`)**: Structural cards, analytical panels, document viewports, chart containers.
* **`rounded-xl` (`10px` to `12px`)**: Flyout drawers, modals, command palette dialogs.
* **`rounded-full` (`9999px`)**: Status pills, role tags, counter dots, avatar rings, live indicator badges.

---

## 5. Shadows & Elevation

Visual depth is achieved through surgical perimeter strokes, micro-tonal shifts, and minimal ambient lighting rather than heavy drop shadows:

* **Level 0 (Flat Ground)**:
  `box-shadow: none;` — Canvas background (`#FCF8FB`).
* **Level 1 (Structural Cards & Tables)**:
  `box-shadow: none; border: 1px solid rgba(9, 9, 11, 0.06);`
* **Level 1 (Hover / Interactive State)**:
  `box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.05); border-color: rgba(79, 70, 229, 0.35);`
* **Level 2 (Floating Overlays, Dropdowns, Blades)**:
  `box-shadow: 0 12px 32px -4px rgba(0, 0, 0, 0.08); border: 1px solid rgba(9, 9, 11, 0.08);`
* **Level 3 (Modals / Security Barriers)**:
  `box-shadow: 0 20px 48px -8px rgba(0, 0, 0, 0.16); backdrop-filter: blur(8px);`

---

## 6. Borders & Hairlines

* **Light Surfaces**: `1px solid rgba(9, 9, 11, 0.06)` or `#EAE7EA`
* **Subtle Dividers**: `1px solid rgba(9, 9, 11, 0.04)`
* **Active / Focused Hairlines**: `1px solid #4F46E5`
* **Dark Hero Console**: `1px solid rgba(255, 255, 255, 0.10)`
* **Dashed Dropzones**: `2px dashed rgba(79, 70, 229, 0.25)`

---

## 7. Component Specifications

### 7.1 Buttons
* **Primary Button**:
  * Background: `#4F46E5` (Primary Indigo)
  * Hover Background: `#4338CA` with subtle luminescence
  * Text: `#FFFFFF`, `font-size: 14px`, `font-weight: 500`
  * Padding: `8px 16px` (Height: 38px)
  * Radius: `4px`
  * Inset Top Highlight: `box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2)`
* **Secondary / Subdued Button**:
  * Background: `#FFFFFF`
  * Border: `1px solid rgba(9, 9, 11, 0.10)`
  * Text: `#1C1B1D`, `font-size: 14px`, `font-weight: 500`
  * Hover: Background `#F6F2F5`, Border `rgba(9, 9, 11, 0.18)`
  * Height: 38px
* **Compact / Table Action Button**:
  * Height: `30px` to `32px`, padding: `4px 10px`, `font-size: 12px`
* **AI Action / Synthesis Button**:
  * Background: `rgba(79, 70, 229, 0.06)`
  * Border: `1px solid rgba(79, 70, 229, 0.30)`
  * Text: `#4F46E5`, accompanied by Lucide `Sparkles` icon

### 7.2 Inputs & Form Controls
* **Default Input**:
  * Background: `#FFFFFF`
  * Border: `1px solid rgba(9, 9, 11, 0.12)`
  * Radius: `4px`
  * Height: `38px` (Compact: `34px`)
  * Padding: `8px 12px`
  * Text: `14px Inter`
  * Placeholder: `#777587`
* **Active / Focused Input**:
  * Border: `1px solid #4F46E5`
  * Glow Ring: `box-shadow: 0 0 0 1px #4F46E5`
* **Terminal Search Bar (Hero / Global)**:
  * Height: `44px` to `48px`
  * Radius: `8px`
  * Background: `#FFFFFF` with `1px solid rgba(9, 9, 11, 0.10)`
  * Trailing Keyboard Shortcut: `⌘K` or `Ctrl+K` rendered in `label-mono-sm` pill
* **Dropdown Selectors**:
  * Clean chevron indicator, matching input height and border spec

### 7.3 Cards & Data Surfaces
* **Standard Data Card**:
  * Background: `#FFFFFF`
  * Border: `1px solid rgba(9, 9, 11, 0.06)`
  * Radius: `8px`
  * Padding: `20px` to `24px`
* **Hero KPI Card**:
  * Structure: Muted top label (`label-mono-sm`, uppercase), oversized bold metric (`48px` to `56px`), bottom trend indicator with sparkline or delta pill
* **High-Contrast Comparison Card ("A vs B" Discrepancy)**:
  * Generous `24px` padding
  * Centerpiece: Side-by-side comparison with oversized `42px` numbers
  * Clear provenance captions (e.g. *Lab Tested ADB* vs *Ministry Dispatch Claim*)
  * Bottom delta pill (e.g. `+6.4% discrepancy`) + direct action resolution buttons

### 7.4 Data Tables
* **Layout**: Edge-to-edge within card containers
* **Header Row**:
  * Height: `38px`
  * Background: `#F6F2F5`
  * Typography: `label-mono-sm` (11px uppercase, tracking `+0.04em`, color `#777587`)
  * Border-bottom: `1px solid rgba(9, 9, 11, 0.06)`
* **Data Rows**:
  * Minimum height: `48px` (High-density inspection: `40px`)
  * Border-bottom: `1px solid rgba(9, 9, 11, 0.04)`
  * Hover state: Background sweeps to `#FBF9FB` with a `2px` Electric Indigo left indicator
  * Numerical data aligned right with monospace tabular font

### 7.5 Badges & Status Pills
* **Geometry**: Fully circular `rounded-full` (`9999px`)
* **Typography**: `11px` / `12px` font weight `600`
* **Padding**: `3px 10px`
* **Types**:
  * **Verified / Approved**: Green background (`#DCFCE7`), green text (`#15803D`)
  * **Starred / Urgent**: Amber background (`#FEF3C7`), amber text (`#B45309`) with countdown tag (`Due in 36h`)
  * **Discrepancy / Red Flag**: Red background (`#FEE2E2`), red text (`#B91C1C`)
  * **AI Draft / Under Review**: Soft violet background (`#EDE9FE`), violet text (`#5B21B6`)
  * **Subsidiary Code**: Neutral slate background (`#F1F5F9`), slate text (`#334155`) with mono code (e.g. `MCL`, `ECL`, `CMPDI`)

### 7.6 Navigation & Command Rails
* **Command Sidebar (260px fixed)**:
  * Background: `#FFFFFF`
  * Right Border: `1px solid rgba(9, 9, 11, 0.06)`
  * Brand Header: Centered geometric coal strata logomark + "MineIQ" bold title
  * Nav Item Height: `40px`
  * Default Item: `#464555` text, monochrome Lucide icon, hover background `#F6F2F5`
  * Active Item: Background `rgba(79, 70, 229, 0.06)`, Text `#4F46E5`, Font weight `600`, Active left indicator: `3px solid #4F46E5`
* **Top Utility Bar**:
  * Height: `56px`
  * Background: `#FFFFFF` with bottom border `1px solid rgba(9, 9, 11, 0.06)`
  * Components: Breadcrumb navigation, Global search input, Subsidiary Context Switcher, User RBAC pill with avatar

### 7.7 Modals & Drawers
* **Modal Dialog**:
  * Max width: `560px` to `720px`
  * Radius: `10px`
  * Background: `#FFFFFF`
  * Backdrop: `rgba(15, 23, 42, 0.45)` with `backdrop-filter: blur(4px)`
* **Slide-out Context Drawer / Blade**:
  * Width: `380px` to `480px`
  * Anchored to right edge, full height
  * Smooth translation transition (`cubic-bezier(0.16, 1, 0.3, 1)`)
  * Border-left: `1px solid rgba(9, 9, 11, 0.08)`

### 7.8 Steppers & Progress Pipelines
* **Horizontal Pipeline Stepper (Documents Ingestion)**:
  * 5 Stages: *Upload* → *OCR & Vectorize* → *Validate & Stratum Mapping* → *Classify* → *Intelligence Report*
  * Connecting line: `2px` track with progress fill
  * Completed stage: Solid emerald dot with white checkmark
  * Active stage: Glowing electric indigo ring with live pulse animation
  * Pending stage: Neutral grey outline dot

---

## 8. System States

### 8.1 Loading States
* **Shimmer / Skeleton**: Linear gradient sweep (`linear-gradient(90deg, #F0EDF0 0%, #FFFFFF 50%, #F0EDF0 100%)`) with a 1.4s infinite cycle.
* **Micro-Spinners**: Dual-tone circular SVG spinner in `#4F46E5`.
* **Telemetry Streaming**: Live pulsing dot (4px) in emerald or indigo indicating active ingestion.

### 8.2 Empty States
* Clean centered layout with 48px muted Lucide icon in circular slate pill.
* Headline in `headline-sm` (`16px`, semibold).
* Subhead in `body-sm` (`13px`, muted).
* Single clear CTA button (e.g. *"Upload First Geological Log"* or *"Clear Search Filters"*).

### 8.3 Error & Discrepancy States
* High-visibility banner or card boundary in `#EF4444`.
* Plain English explanation with highlighted variance delta.
* Specific corrective actions provided (e.g., *"Flag for CMPDI Field Re-assay"*, *"Request Weighbridge Re-scan"*).

---

## 9. Charts & Visualizations

* **Palette for Multi-Series Charts**:
  * Series 1 (Reported / Pit-head): Deep Indigo `#4F46E5`
  * Series 2 (Railway Weighed / Actual): Slate Gray `#64748B` or Electric Indigo `#6063EE`
  * Series 3 (Positive Delta): Emerald `#10B981`
  * Series 4 (Discrepancy Delta): Crimson `#EF4444`
* **Gridlines**: Ultra-faint `rgba(9, 9, 11, 0.04)` dashed lines; no heavy black axes.
* **Tooltips**: Sleek dark slate pill (`#0F172A`) with pure white monospace labels.
* **Specialized Visualizers**:
  * **Entity Cluster / Word Cloud**: Single-accent slate-to-indigo sizing based on extraction frequency.
  * **Donut Chart**: Central oversized metric (e.g. `142.8k`) with clean outer ring segments and side legend.

---

## 10. Iconography

* **Library**: `lucide-react`
* **Stroke Width**: `1.75px` to `2px` for crisp high-density legibility.
* **Default Icon Size**: `18px` in buttons and tables; `20px` in navigation; `24px` in hero metrics.
* **Color**: Inherits text color or is tinted with semantic token (`#4F46E5`, `#10B981`, `#F59E0B`, `#EF4444`).

---

## 11. Responsive Behavior & Breakpoints

* **Desktop Wide (`>= 1440px`)**:
  * Fixed 260px collapsible command rail.
  * Flexible 12-column analytical grid with 24px gutters.
  * Synchronized dual-pane views (e.g. PQ Copilot 40% / 60%, Document Split-Viewer 50% / 50%).
* **Desktop / Laptop (`1024px – 1439px`)**:
  * Sidebar can collapse to a 64px icon rail.
  * Right context blades convert to sliding overlay sheets.
* **Tablet (`768px – 1023px`)**:
  * 8-column layout with 16px gutters.
  * Master-detail panes toggle via tab switches rather than split-screen.
* **Mobile (`< 768px`)**:
  * Single-column stacked stream.
  * Tables convert to swipeable inspection cards with primary key sticky anchors.
  * Minimum touch target of 40px maintained.

---

## 12. Component-Level Visual Rules & Anti-Patterns

### Strict Rules:
1. **Never use generic browser-default colors** (plain red, blue, green). Always adhere to the curated Indigo/Slate/Emerald/Amber/Crimson palette.
2. **Never place 1px heavy black borders** around sections. Use subtle `rgba(9, 9, 11, 0.06)` hairlines or background tonal shifts.
3. **No bureaucratic clutter**: Strictly exclude fake legal warnings, intrusive NIC stamps, or generic disclaimer text unless specifically representing a formal parliamentary brief.
4. **Data prominence**: Let the numbers do the heavy lifting visually. Use oversized bold typography (`42px`–`56px`) for critical figures and discrepancies.
5. **Monospace for figures**: Always format metrics, coordinates, and percentages with `font-variant-numeric: tabular-nums` and `JetBrains Mono`.
