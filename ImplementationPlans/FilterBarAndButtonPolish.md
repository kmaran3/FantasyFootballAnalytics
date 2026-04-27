# Filter Bar & Button Polish — Implementation Plan

**Date:** 2026-03-24
**Branch:** Krishna
**Status:** Draft — one open question (marked ⚠️)

---

## Summary of Changes

| # | Change | Files |
|---|--------|-------|
| 1 | Custom click-to-open dropdown for Team filter | `rankings.html`, `styles.css` |
| 2 | Custom click-to-open dropdown for Bye Week filter | `rankings.html`, `styles.css` |
| 3 | Move both dropdowns into the same single row as search + position buttons | `rankings.html`, `styles.css` |
| 4 | Widen table and filter bar to fit all controls on one row | `styles.css` |
| 5 | Restyle PPR / Half PPR / Standard buttons to match dark navy theme | `styles.css` |
| 6 | Restyle Save Rankings button to match dark navy theme | `styles.css` |

---

## Open Question

> ⚠️ **Q — PPR / Half PPR / Standard button placement:**
> Currently these sit in the fixed left sidebar. The request is to make them look cleaner. Two options:
> - **(a) Restyle in place** — keep them in the left sidebar, update colors/borders to match the dark navy theme.
> - **(b) Move above the table** — place them as a row of tabs or buttons just above the ranking table, removing the left sidebar entirely.
>
> **Assuming (a) restyle in place** unless told otherwise.

---

## Feature-by-Feature Plan

---

### Change 1 & 2: Custom Multi-Select Dropdowns (Team + Bye Week)

**Problem with current approach:** Native `<select multiple>` requires Ctrl/Cmd+click for multi-select and appears as an always-visible list box — not a click-to-open dropdown.

**New approach:** Custom JS dropdown widgets built from scratch. No external library needed.

**HTML structure per dropdown:**
```html
<div class="custom-dropdown" id="teamDropdown">
  <button class="custom-dropdown-btn" id="teamDropdownBtn">
    Team <span class="dd-arrow">▼</span>
  </button>
  <div class="custom-dropdown-panel" id="teamDropdownPanel" style="display:none;">
    <div class="dd-option dd-clear-option" data-value="">Clear All</div>
    <div class="dd-option" data-value="ARI">ARI</div>
    <div class="dd-option" data-value="ATL">ATL</div>
    <!-- ... all 32 teams ... -->
  </div>
</div>
```

**Behavior:**
- Clicking the button toggles the panel open/closed
- Clicking outside any open panel closes all panels
- Each row in the panel is a normal click (no Ctrl needed) — clicking toggles selection on/off
- Selected items get a checkmark (✓) and highlighted background
- Button label updates to show count: `Team (3) ▼` when 3 teams are selected, `Team ▼` when none
- "Clear All" row at top of panel deselects everything and resets label
- Arrow rotates 180° when panel is open (CSS transition)

**JS state:** Replace the old `$('#teamFilter').val()` calls with a simple `Set` tracking selected values:
```javascript
var selectedTeams  = new Set();
var selectedByeWeeks = new Set();
```

**`applyFilters()` change:** Replace `$('#teamFilter').val()` with `Array.from(selectedTeams)`.

**Panel positioning:** `position: absolute` below the trigger button, `z-index: 1100` (above everything else). Max-height with scroll for team list (32 items).

---

### Change 3: Single-Row Filter Bar

**Goal:** All controls on one line:
```
[Search...] [All Positions] [QB] [RB] [WR] [TE] [K] [DEF] [Deep Dive] [Team ▼] [Bye Week ▼]
```

**Changes:**
- Remove `.filter-bar-row-2` (the second row)
- Remove `.filter-bar-row` wrapper — flatten back to one flex row in `.filter-bar-inner`
- `.filter-bar-inner` → `flex-direction: row`, `align-items: center`, `flex-wrap: wrap`
- Add the two custom dropdown divs directly into the `.filter-buttons` group or after it
- Remove `.filter-hint` text entirely (no Ctrl/Cmd needed anymore)
- The `.custom-dropdown` sits inline like another button

**`.filter-bar-inner` layout:**
```css
.filter-bar-inner {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;  /* fallback if viewport too narrow */
}
```

---

### Change 4: Table and Filter Bar Width

**Current width:** `table { width: 65%; }` and `.filter-bar-inner { width: 65%; }`

**Problem:** With 8 position buttons + search + 2 dropdown triggers on one row, 65% may be too narrow — items wrap onto a second line or overflow.

**New width:** Increase both to **78%**. This gives enough room for all controls on a single row at standard laptop screen widths (1280px+), while keeping the left and right panels visible.

**Changes:**
```css
table { width: 78%; }
.filter-bar-inner { width: 78%; }
```

The left panel (130px fixed, left: 40px) and right panel (160px fixed, right: 40px) already sit outside the content flow, so widening the table won't overlap them at 78%.

---

### Change 5: PPR / Half PPR / Standard Button Restyle

**Current:** `background-color: #444`, cream text, active = cream bg + dark text. Left panel is `#555`.

**New (assuming restyle-in-place):**

| State | Background | Text | Border |
|-------|-----------|------|--------|
| Default | `#16213e` | `#a0b8ff` | `1px solid #2a2a5e` |
| Hover | `#0f3460` | `#e0e0e0` | `1px solid #4a6aae` |
| Active (current page) | `#f8f39fee` | `#1a1a2e` | none |

Left panel container: change from `#555` to `#0d1b2a` to match deep dark theme.

Left panel `h2`: change to `#a0b8ff` (the light blue accent used in deep dive section titles).

---

### Change 6: Save Rankings Button Restyle

**Current:** Cream/yellow `#f8f39fee` background, dark `#333` text — stands out but clashes with dark theme.

**New:** Match the dark navy theme while keeping it visually prominent as an action button.

| State | Background | Text | Border |
|-------|-----------|------|--------|
| Default | `#16213e` | `#f8f39fee` | `1px solid #f8f39fee` |
| Hover | `#0f3460` | `#fff` | `1px solid #fff` |
| Active (pressed) | `#0d1b2a` | `#f8f39fee` | — |

The cream border gives it a distinct "call to action" feel without the jarring cream background.

Right panel container: change from `#555` to `#0d1b2a`. Right panel `h2`: change to `#a0b8ff`.

Saved ranking links: change from `#444` bg to `#16213e`, same `a0b8ff` accent for active state text.

---

## Implementation Sequence

1. CSS changes for left panel, right panel, ranking-type buttons, save-rankings button (Change 5 & 6)
2. Widen table and filter bar (Change 4)
3. Build custom dropdown HTML + JS + CSS, replace `<select>` elements (Changes 1 & 2)
4. Flatten filter bar to single row (Change 3)
5. Remove old `.filter-bar-row-2`, `.filter-select`, `.filter-label`, `.filter-hint` CSS (cleanup)

---

## Files Changed

| File | Changes |
|------|---------|
| `webapp/templates/rankings.html` | Replace `<select>` elements with custom dropdown HTML; flatten filter bar to one row; update JS (`selectedTeams` Set, `applyFilters`, dropdown open/close logic) |
| `webapp/static/css/styles.css` | Widen table + filter bar; custom dropdown styles; panel + option styles; left/right panel dark theme; ranking-type-btn restyle; save-ranking-btn restyle |

---

## CSS Classes to Add

| Class | Purpose |
|-------|---------|
| `.custom-dropdown` | Relative-positioned wrapper for trigger + panel |
| `.custom-dropdown-btn` | Trigger button (styled like position filter buttons) |
| `.custom-dropdown-btn.open` | Button state when panel is visible (arrow rotated) |
| `.dd-arrow` | The ▼ icon, CSS-rotated when open |
| `.custom-dropdown-panel` | The floating list panel |
| `.dd-option` | Each selectable item row |
| `.dd-option.selected` | Selected state (checkmark + highlight) |
| `.dd-clear-option` | "Clear All" row at top |

## CSS Classes to Remove

| Class | Reason |
|-------|--------|
| `.filter-bar-row` | No longer needed (single row) |
| `.filter-bar-row-2` | Removed (no second row) |
| `.filter-dropdown-group` | Replaced by `.custom-dropdown` |
| `.filter-label` | Label moved into button text |
| `.filter-select` | Native select replaced |
| `.filter-hint` | Ctrl/Cmd instruction no longer needed |
