# Knowledge Fairy UI

The shared system skin lives in `frontend/src/styles/fairy-theme.css`, imported
last by `frontend/src/main.ts`. It replaces the earlier Aurora treatment.

## Coverage

- Shell: porcelain navigation tiles, pastel active states, mascot companion link.
- Library: illustrated welcome, folder-shaped cards, tinted metrics, import zone.
- Retrieval: soft configuration panel, inset query field, evidence cards.
- Chat: mascot avatar, welcome illustration, suggestion cards, paper-like answers,
  blue question bubbles and a raised composer.
- Usage: pastel metrics, frosted filters, coordinated charts and data tables.
- Providers: porcelain service cards, inset configuration summaries, action buttons.
- Dialogs and file preview: matching backgrounds, blur and borders. Existing
  MacDialog animation/lifecycle remains in use for create/edit forms.
- Controls: pressed states, keyboard focus, disabled states, reduced motion and
  responsive layouts share the same theme.

`FairyIcon.vue` composes porcelain glyph tiles or a mascot portrait with semantic
badges. Small action icons retain their recognizable glyphs.

## Generated assets

Generated with the built-in image_gen tool, using the supplied character as a
reference. Transparent alpha preserved. Pillow was used only for the requested
resizing and WebP compression, quality 82, method 6. No remote image requests or
new runtime dependencies.

| Static file | Dimensions | Bytes |
| --- | --- | --- |
| `/mascot/knowledge-fairy.webp` | 616 × 640 | 64,936 |
| `/mascot/fairy-avatar.webp` | 192 × 192 | 15,402 |

Combined: 80,338 bytes (~78.5 KiB), down from 3,277,906 bytes of PNG (~97.5%).
The originals remain in the generation output directory; only compressed assets
ship in `frontend/public/mascot/`.

## Generation prompts

### Knowledge fairy

Use case: stylized-concept. Generate a single reusable mascot illustration asset
for a knowledge management application using the attached image as character
identity and style reference. Same adorable polished 3D chibi girl doll, long
flowing ash brown hair, very large warm brown eyes, pale powder-blue cape dress,
cream ankle boots, small pink ribbon. Full body, floating slightly, holding a
luminous star wand in one hand and an open little blue book in the other. Gentle
welcoming expression. Preserve recognizable identity, elegant toy sculpture
materials, pearlescent highlights, soft warm peach rim light and cool teal fill.
Isolated on genuinely transparent background, no floor, no text, no border, no
watermark, no backdrop. Clean silhouette and restrained little star sparkles close
to wand; generous padding. Asset must work at 320px and as a smaller UI mascot.
Please save generated image and return its local file path for use in the project.

### Fairy avatar

Create one app mascot avatar icon, based exactly on the preceding generated girl's
identity: same long ash-brown hair with curved cowlick, huge brown eyes, pale blue
cape, pink ribbon. This is a square head-and-shoulders portrait of the same 3D chibi
doll, cheerful gentle expression, carrying a tiny glowing star wand beside her
cheek. Large face occupying 70% of canvas, clear at 48px. Luxurious ceramic and soft
fabric materials, powder blue, cream, blush pink highlights with teal bounce
light. Genuinely transparent background, isolated cutout, no disc, no border, no
text, no watermark. Single avatar asset only, not a sheet. Provide local saved
file path.

## Validation

Production build, existing streaming suite (9 tests), existing interaction/dialog
suite (14 tests). Browser visual review remains outstanding: the browser runtime
reported no connected browser during this session.
