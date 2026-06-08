# SVG Diagram Generation Reference

Detailed guidance for generating content-driven SVG diagrams that are directly
embedded in the HTML output.

## Core Principle

Every SVG must be **derived from the chapter's real content**. Keywords, labels,
arrows, and structure all come from what was actually said and shown in the video.
Never use generic "Step 1, Step 2, Step 3" or decorative diagrams.

## Type Selection Decision Tree

```
Content contains a sequence of actions?
  → Flowchart / Step path (numbered boxes with arrows)

Content explains how components relate?
  → Relationship / Layer diagram (hierarchical or networked boxes)

Content shows progression over time?
  → Timeline (horizontal axis with markers)

Content compares two or more things?
  → Matrix / Side-by-side comparison (columns, checkmarks/X)

Content warns about risks or mistakes?
  → Checklist / Decision tree (branching paths, warning icons)

Content presents numbers/metrics?
  → Simplified chart (bars, lines, small data table)

Content traces cause and effect?
  → Causal chain (linked nodes with directional arrows)
```

## SVG Technical Constraints

- `viewBox="0 0 680 <height>"` — fixed width, flexible height
- Maximum height: 500px (reflow content if taller)
- Font: system-ui, sans-serif, at least 13px for readability
- Colors: use the page's CSS variables or consistent hex values
- Background: `#f8f9fa` with a 1px `#e0e0e0` border
- All text must be in Chinese where possible, matching the document language
- Use `<text>`, `<rect>`, `<line>`, `<path>`, `<polygon>`, `<circle>` elements
- NO external fonts, NO images within SVG, NO scripts

## Styling Constants

```css
/* To be used as fill/stroke values */
--svg-bg: #f8f9fa;
--svg-border: #dee2e6;
--svg-text: #212529;
--svg-accent: #2563eb;
--svg-accent-light: #dbeafe;
--svg-warning: #f59e0b;
--svg-danger: #ef4444;
--svg-success: #10b981;
--svg-node-bg: #ffffff;
```

## Examples by Type

### Flowchart (process/steps)
```svg
<svg viewBox="0 0 680 280" xmlns="http://www.w3.org/2000/svg">
  <rect width="680" height="280" fill="#f8f9fa" rx="6"/>
  <!-- Step nodes connected by arrows -->
  <!-- Include the actual step descriptions from the video -->
</svg>
```

### Timeline (temporal progression)
```svg
<svg viewBox="0 0 680 200" xmlns="http://www.w3.org/2000/svg">
  <!-- Horizontal timeline axis with event markers -->
  <!-- Each marker labeled with actual video timestamps -->
</svg>
```

### Comparison Matrix
```svg
<svg viewBox="0 0 680 350" xmlns="http://www.w3.org/2000/svg">
  <!-- Two-column layout comparing features/methods -->
  <!-- Use checkmarks (✓) and X marks (✗) -->
</svg>
```

### Decision Tree / Checklist
```svg
<svg viewBox="0 0 680 400" xmlns="http://www.w3.org/2000/svg">
  <!-- Branching paths with decision diamonds -->
  <!-- Warning icons at critical decision points -->
</svg>
```

### Causal Chain
```svg
<svg viewBox="0 0 680 220" xmlns="http://www.w3.org/2000/svg">
  <!-- Linked nodes showing cause → effect relationships -->
  <!-- Directional arrows with labels for each link -->
</svg>
```

## Annotation Convention

Every SVG must be wrapped in a `<figure>` with a `<figcaption>`:

| Label | Meaning |
|-------|---------|
| `「图解」` | SVG diagram — explains relationships/concepts |
| `「视频时间戳 HH:MM:SS」` | Screenshot — shows what was on screen |

Never mix these labels. SVGs always get `「图解」`, screenshots always get
`「视频时间戳 HH:MM:SS」`.
