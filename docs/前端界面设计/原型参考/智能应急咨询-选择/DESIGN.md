---
name: The Trusted Ember
colors:
  surface: '#faf9fe'
  surface-dim: '#dad9df'
  surface-bright: '#faf9fe'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f4f3f8'
  surface-container: '#eeedf3'
  surface-container-high: '#e9e7ed'
  surface-container-highest: '#e3e2e7'
  on-surface: '#1a1b1f'
  on-surface-variant: '#554334'
  inverse-surface: '#2f3034'
  inverse-on-surface: '#f1f0f5'
  outline: '#887361'
  outline-variant: '#dbc2ad'
  surface-tint: '#8c5000'
  primary: '#8c5000'
  on-primary: '#ffffff'
  primary-container: '#ff9500'
  on-primary-container: '#643700'
  inverse-primary: '#ffb874'
  secondary: '#5f5e60'
  on-secondary: '#ffffff'
  secondary-container: '#e2dfe1'
  on-secondary-container: '#636264'
  tertiary: '#005bc1'
  on-tertiary: '#ffffff'
  tertiary-container: '#86aeff'
  on-tertiary-container: '#003f8a'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#ffdcbf'
  primary-fixed-dim: '#ffb874'
  on-primary-fixed: '#2d1600'
  on-primary-fixed-variant: '#6a3b00'
  secondary-fixed: '#e4e2e4'
  secondary-fixed-dim: '#c8c6c8'
  on-secondary-fixed: '#1b1b1d'
  on-secondary-fixed-variant: '#474649'
  tertiary-fixed: '#d8e2ff'
  tertiary-fixed-dim: '#adc6ff'
  on-tertiary-fixed: '#001a41'
  on-tertiary-fixed-variant: '#004493'
  background: '#faf9fe'
  on-background: '#1a1b1f'
  surface-variant: '#e3e2e7'
typography:
  headline-lg:
    fontFamily: Hanken Grotesk
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 40px
    letterSpacing: -0.02em
  headline-lg-mobile:
    fontFamily: Hanken Grotesk
    fontSize: 28px
    fontWeight: '700'
    lineHeight: 34px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Hanken Grotesk
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  body-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-sm:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  label-md:
    fontFamily: JetBrains Mono
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.05em
  label-sm:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 14px
    letterSpacing: 0.05em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  base: 4px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  gutter: 16px
  margin-mobile: 16px
  margin-desktop: 48px
---

## Brand & Style
The design system is built for high-stakes emergency response environments where clarity and reassurance are paramount. The brand personality, "The Trusted Ember," represents a steady, reliable light in the dark—warmth that protects rather than burns.

The design style is **Corporate / Modern** with **High-Contrast** functional elements. It prioritizes utility and rapid information processing while using a sophisticated, vibrant palette to evoke a sense of urgent care. The interface maintains a disciplined structure to ensure users feel in control during stressful situations, balancing professional reliability with an approachable, human-centric warmth.

## Colors
The color palette is centered around a vibrant "Flame Orange-Yellow" (`#FF9500`), meticulously tuned to remain bright and glowing without any muddy or brown undertones. This primary color acts as a beacon within the UI, signifying action and presence.

- **Primary:** A luminous, campfire-orange used for key actions and essential branding.
- **Primary Container:** A very light, warm wash used for background surfaces that need to feel connected to the primary brand without overwhelming the user.
- **Secondary:** A deep, near-black neutral provides the "charcoal" contrast, ensuring the primary color pops and remains legible.
- **Tertiary:** A crisp blue used sparingly for informative or systemic links to prevent "warning fatigue" from too much orange.
- **Functional Colors:** Success, Warning, and Error colors follow standard safety conventions but are calibrated for high vibrancy to match the primary "Ember" energy.

## Typography
Typography is optimized for legibility under duress. **Hanken Grotesk** provides a sharp, contemporary authority for headlines. **Inter** is used for body copy due to its exceptional readability and neutral tone. **JetBrains Mono** is utilized for labels, timestamps, and technical data points, providing a precise, "instrument-panel" feel that reinforces the app's professional utility.

For mobile devices, headlines scale down slightly to ensure maximum information density without sacrificing the hierarchy.

## Layout & Spacing
The design system utilizes a **Fixed Grid** on desktop (12 columns) and a **Fluid Grid** on mobile (4 columns). The spacing rhythm is based on a 4px baseline, with 16px being the standard atomic unit for gutters and internal padding.

- **Mobile:** 16px side margins with 16px gutters. Elements usually stack vertically.
- **Tablet/Desktop:** Content is centered in a max-width container (1200px). Margins expand to 48px to provide breathing room and focus.
- **Rhythm:** Use `md` (16px) for most component spacing and `lg` (24px) to separate distinct content sections.

## Elevation & Depth
Depth is signaled through **Tonal Layers** rather than heavy shadows. The background is typically a very light gray or white, with "Container" elements using subtle off-whites or the `primary_container` tint to denote hierarchy.

When shadows are necessary for high-priority modals or floating action buttons, use **Ambient Shadows**: ultra-diffused (20px-40px blur), low opacity (8-10%), and slightly tinted with the primary orange to simulate a warm glow reflecting off the surface. This creates a soft, approachable depth that avoids the "dirty" look of standard black shadows.

## Shapes
The shape language uses **Rounded** corners to balance the high-contrast colors with a sense of safety and approachability. 

- Standard components (Buttons, Inputs) use a 0.5rem (8px) radius.
- Cards and large containers use 1rem (16px).
- Status indicators or "Live" badges may use pill-shapes to distinguish them from interactive buttons.

## Components
- **Buttons:** Primary buttons use the vibrant Flame Orange with white text for maximum "glow" effect. Secondary buttons use an outline of the primary color.
- **Inputs:** High-visibility borders (2px) when focused, using the primary color to guide the user's attention.
- **Chips:** Used for filtering emergency categories. Active chips use a saturated orange background; inactive chips use a subtle neutral-gray.
- **Cards:** White surfaces with a very thin, low-contrast neutral border. No heavy shadows; depth is achieved via the `primary_container` background for active states.
- **Emergency FAB:** A large, floating action button for "SOS" or "Report" should always use the Primary color with a subtle warm glow shadow to ensure it is the first thing a user sees.
- **Lists:** Clean, tight spacing with 1px dividers. Use the `label-sm` (Monospaced) for timestamps or ID numbers to maintain a professional, organized look.