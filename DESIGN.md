---
name: Find the right care
description: A flat referral directory with evidence available beneath each facility.
colors:
  accent: "#104963"
  accent-hover: "#0a374c"
  warning: "#783a26"
  warning-surface: "#fff3ed"
  warning-border: "#ad6b54"
  paper: "#fdfdfb"
  white: "#fff"
  ink: "#172a34"
  muted: "#515e64"
  rule: "#c9cfcd"
  control: "#68777b"
  focus: "#176d90"
typography:
  display:
    fontFamily: 'Georgia, "Times New Roman", serif'
    fontSize: "3.25rem"
    fontWeight: 700
    lineHeight: 1.06
    letterSpacing: "-.037em"
  wordmark:
    fontFamily: 'Georgia, "Times New Roman", serif'
    fontSize: "2rem"
    fontWeight: 700
    lineHeight: 1.12
    letterSpacing: "-.032em"
  title:
    fontFamily: 'Georgia, "Times New Roman", serif'
    fontSize: "2rem"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-.032em"
  body:
    fontFamily: "system-ui, -apple-system, sans-serif"
    fontSize: ".9375rem"
    lineHeight: 1.55
  metadata:
    fontFamily: "system-ui, -apple-system, sans-serif"
    fontSize: ".875rem"
    lineHeight: 1.55
  label:
    fontFamily: "system-ui, -apple-system, sans-serif"
    fontSize: ".9375rem"
    fontWeight: 650
  button:
    fontFamily: "system-ui, -apple-system, sans-serif"
    fontSize: "1rem"
    fontWeight: 650
    lineHeight: 1.3
rounded:
  control: "6px"
  circle: "50%"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "20px"
  xxl: "24px"
  xxxl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.white}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
    height: "42px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-search:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.white}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "10px 25px"
    height: "46px"
  button-replay:
    backgroundColor: "transparent"
    textColor: "{colors.accent}"
    rounded: "{rounded.control}"
    padding: "10px 0"
    height: "42px"
  input-search:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "9px 12px"
    height: "46px"
  select-language:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "9px 24px 9px 10px"
    height: "40px"
  disclosure:
    textColor: "{colors.accent}"
    padding: "8px 0"
  facility-row:
    textColor: "{colors.ink}"
    padding: "24px 0"
  emergency-guidance:
    backgroundColor: "{colors.warning-surface}"
    textColor: "{colors.warning}"
    padding: "16px 18px"
  brand-mark:
    textColor: "{colors.accent}"
    rounded: "{rounded.circle}"
    size: "28px"
---

# Design System: Find the right care

## Overview

The interface reads as a referral directory. A paper-white canvas, dark serif headings, petrol controls, and thin gray rules give location, care need, and facility names a clear order. A small route mark sits beside the wordmark.

Facility rows place the evidence status and its explanation beside the follow-up action. Supporting claims and source links open beneath the same result.

## Colors

### Primary

Petrol ties together primary actions, disclosures, source links, the route mark, and standard evidence statuses. A darker petrol marks hover on buttons and links. A separate blue outline identifies keyboard focus.

### Secondary

Rust marks withheld result statuses. Emergency guidance pairs rust text with a pale warm surface and a rust border. Both states name the condition in text.

### Neutral

Paper white is the page ground. White fields are defined by the stronger control border. Ink carries headings and primary copy, muted slate carries metadata and explanations, and gray rules separate groups and rows.

## Typography

Georgia with Times New Roman fallback sets the wordmark, the search heading, and facility names. The system sans-serif sets labels, actions, metadata, and evidence copy. Ranks and facility metadata use tabular numerals. Explanations and follow-up prompts are capped at `72ch`, and evidence and replay copy at `75ch`.

## Layout

The centered shell is capped at `1280px` with at least `48px` of gutter on each side above the tablet breakpoint. The masthead places the language picker opposite the wordmark. Search uses two equal fields and an action column. Facility rows pair a flexible text column with an action column capped at `13rem`. Open evidence spans the row.

At `850px` and below, gutters shrink to `24px`, the query heading drops to `2.75rem`, and the replay line can wrap. At `650px` and below, gutters shrink to `16px`. Search, results, and footer stack, the search action fills the width, and the phone action aligns with the facility text. The query heading drops to `2.125rem` and facility names to `1.625rem`.

## Elevation & Depth

One-pixel rules and vertical spacing define the masthead, search, results, and expanded evidence on a flat canvas. The emergency panel uses a tinted surface and border for emphasis.

## Shapes

Inputs, selects, and buttons have gently rounded corners. Facility rows and the emergency panel have square edges. The route mark uses a circular outline around a clipped directional pointer.

## Components

- **Filled action** uses white type and a petrol background. The search variant matches the fields’ minimum height. A darker fill marks hover, and an in-progress action reduces opacity and shows a wait cursor.
- **Replay action** uses an underlined petrol label on a transparent button. It sits alongside the replay note and can wrap below it on smaller screens.
- **Fields and language picker** use white fill and a gray control border. The picker keeps the browser’s native select affordance. Focus adds a `2px` outline with a `4px` offset.
- **Facility row** leads with the name and an inline rank when present, followed by muted location and distance metadata. Evidence status, explanation, and follow-up prompt stay with the facility. The phone action stacks beneath the facility text on mobile.
- **Evidence disclosure** uses a petrol summary with a native marker and an underline on hover. Expanded source entries sit beneath the facility and use rules to separate claims. Links wrap in place.
- **Emergency guidance** uses a warm bordered panel with a bold heading and an underlined call link in the same rust as the guidance.
