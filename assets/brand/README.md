# Pawgrab brand assets

The Pawgrab mascot and wordmark, in light/dark variants, as transparent SVG and PNG
(@1x/@2x). Overview: [`showcase.png`](showcase.png).

## Assets

| Asset | Use | Files |
|-------|-----|-------|
| **Banner** 1500×500 | README / repo header | `pawgrab-banner-{light,dark}.svg` · `png/` |
| **Social** 1280×640 | GitHub social preview (PNG only) | `png/pawgrab-social-{light,dark}@2x.png` |
| **Lockup — horizontal** | compact logo beside text | `pawgrab-lockup-horizontal-{light,dark}.svg` |
| **Lockup — stacked** | square-ish logo | `pawgrab-lockup-stacked-{light,dark}.svg` |
| **Mark** | icon only, favicon, avatar | `pawgrab-mark-{light,dark}.svg` |

Use the **light** variant on light backgrounds, **dark** on dark (the dark mark adds a
cream rim so the outline survives).

## Palette

| Token | Hex | Role |
|-------|-----|------|
| cream | `#faf3e0` | mascot body / text on dark |
| orange | `#fdcea4` | mascot markings |
| accent L | `#d9824a` | accent on light bg |
| accent D | `#f5a462` | accent on dark bg |
| blush | `#f7a398` | cheeks / highlight |
| plum | `#705462` | wordmark / text on light |
| bg light | `#f6eee2` | light background |
| bg dark | `#1d1820` | dark background |

## README banner (auto light/dark)

```html
<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/pawgrab-banner-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="assets/brand/pawgrab-banner-light.svg">
    <img alt="Pawgrab" src="assets/brand/pawgrab-banner-light.svg" width="100%">
  </picture>
</p>
```

## Social preview

GitHub → **Settings → General → Social preview** → upload
`png/pawgrab-social-light@2x.png` (or `-dark`). GitHub does not accept SVG there.
