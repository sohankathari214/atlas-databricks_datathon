---
name: Find the right care
description: A flat referral directory with evidence available beneath each facility.
colors:
  canvas: "#ffffff"
  surface: "#ffffff"
  search-surface: "#fff2f8"
  ink: "#2a1727"
  muted: "#685163"
  rule: "#e7d6e1"
  control: "#947a8c"
  accent: "#9f175f"
  accent-hover: "#771244"
  action: "#af1767"
  action-hover: "#8d1353"
  action-text: "#fff"
  rose: "#a21d68"
  focus: "#b52474"
  selection: "#f9d5e8"
  warning: "#8e251d"
  warning-border: "#b14b43"
  warning-surface: "#fff0eb"
  confirmed: "#216442"
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
  control: "8px"
  search-panel: "18px"
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
    backgroundColor: "{colors.action}"
    textColor: "{colors.action-text}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
    height: "42px"
  button-primary-hover:
    backgroundColor: "{colors.action-hover}"
  button-search:
    backgroundColor: "{colors.action}"
    textColor: "{colors.action-text}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "10px 25px"
    height: "46px"
  input-search:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "9px 12px"
    height: "46px"
  select-language:
    backgroundColor: "{colors.surface}"
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

The interface reads as a referral directory. A white canvas, dark plum headings, raspberry actions, and blush dividers give location, care need, and facility names a clear order. A small route mark sits beside the wordmark.

Facility rows place the evidence status and its explanation beside the follow-up action. Supporting claims and source links open beneath the same result.

## Colors

### Primary

Raspberry fills primary actions. Deep rose marks links, the compass and keyboard focus.

### Secondary

Warm red marks withheld results and emergency guidance. The alert uses a pale warm surface. Confirmation status uses deep green.

### Neutral

White is the page ground and field surface. Blush frames the search. Dark plum carries headings, muted plum carries metadata, and soft rose dividers separate rows.

## Typography

Georgia with Times New Roman fallback sets the wordmark, the search heading, and facility names. The system sans-serif sets labels, actions, metadata, and evidence copy. Ranks and facility metadata use tabular numerals. Explanations and follow-up prompts are capped at `72ch`, and evidence copy at `75ch`.

## Layout

The centered shell is capped at `1280px` with at least `48px` of gutter on each side above the tablet breakpoint. The masthead places the language picker opposite the wordmark. The blush search panel leads with “Find care near you” and places two equal fields beside the primary action. Facility rows pair a flexible text column with an action column capped at `13rem`. Open evidence spans the row.

At `850px` and below, gutters shrink to `24px`, the query heading drops to `2.75rem`. At `650px` and below, gutters shrink to `16px`. Search, results, and footer stack, the search action fills the width, and the phone action aligns with the facility text. The query heading drops to `2.125rem` and facility names to `1.625rem`.

## Elevation & Depth

One-pixel rules and vertical spacing define the masthead, search, results, and expanded evidence on a flat canvas. The search panel uses a blush fill. Emergency guidance uses a warm surface and dark red text.

## Shapes

Inputs, selects, and buttons have gently rounded corners. Facility rows and the emergency panel have square edges. The route mark uses a circular outline around a clipped directional pointer.

## Components

- **Filled action** uses white type and a raspberry background. The search variant matches the fields’ minimum height. A deeper raspberry fill marks hover, and an in-progress action reduces opacity and shows a wait cursor.
- **Fields and language picker** use white fill and a muted rose border. The picker keeps the browser’s native select affordance. Focus adds a `2px` outline with a `4px` offset.
- **Facility row** leads with the name and an inline rank when present, followed by muted location and distance metadata. Evidence status, explanation, and follow-up prompt stay with the facility. The outlined phone action stacks beneath the facility text on mobile.
- **Evidence disclosure** uses a rose summary with a native marker and an underline on hover. Expanded source entries sit beneath the facility and use rules to separate claims. Links wrap in place. The first source entry uses a 180 ms reveal when reduced motion is off.
- **Emergency guidance** uses a warm bordered panel with a bold heading and an underlined call link in the same dark red as the guidance.
