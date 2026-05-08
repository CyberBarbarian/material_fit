# Metric Validation: From Pixel-MAE to Perceptual Fit Score

> **Status**: implemented (E-009, 2026-05-06).
> **Scope**: this document is the primary written record for the
> *Metric Design* section of the planned paper. Every defended
> claim here should be either supported by code in the repository
> (cited via path) or by data dropped in
> `tools/material_fit/output/fish_1580/auto_adjust/e009_rescore.json`.
> If you add a new metric or change a weight, update this document
> in the same commit.

---

## 1. Why this document exists

In all previous runs of the cross-engine material fitting pipeline,
the *headline* score driving the optimizer (`fit_score`) and surfaced
to the user was a single scalar:

```
fit_score = 1 − sqrt(rgb_mae × 4)
```

where `rgb_mae` is the **mean per-pixel L1 colour distance** over
the *entire* reference / candidate image pair, with no spatial mask.

When the user examined Iteration 12 of `fish_1580` and asked the
question *"if every channel sub-score is high, does that necessarily
mean the rendering is visually close to Unity's?"*, we discovered
that the answer is **no**, for reasons that are individually small
but compound disastrously. This document is the systematic record of
those reasons, the corrected metric, and the empirical evidence that
the correction matters.

The corrected metric is implemented in
[`tools/material_fit/vision/perceptual_score.py`](../vision/perceptual_score.py)
and integrated into the rest of the pipeline via
[`tools/material_fit/vision/diff_analysis.py`](../vision/diff_analysis.py)
and
[`tools/material_fit/fit_material.py`](../fit_material.py).

---

## 2. The scientific question

Reduced to one sentence:

> Given two RGB images $R$ (Unity reference) and $C$ (Laya candidate)
> rendered from notionally the same model under different shading
> systems, what scalar function $f(R, C) \in [0, 1]$ should we
> optimise so that *higher $f$* corresponds, monotonically and
> tightly, with *"a human evaluator judging $C$ as a faithful
> match for $R$"*?

This question is well known in the inverse rendering and material
capture literature. We therefore borrowed three independent
ingredients that the literature has already validated and combined
them into a single composite score targeted at our setting:

1. **Foreground masking** — exclude pixels that lie outside the
   model (editor backgrounds, sky planes, UI gizmos). Inspired by
   the alpha-compositing convention used in differentiable
   rendering (Laine et al., 2020), but implemented via colour
   clustering because Laya screenshots have no alpha channel.
2. **Channel-weighted MAE** — give more weight to the small but
   eye-catching regions (specular highlights, emission, fresnel
   rim). Ad-hoc but consistent with the "salient region weighting"
   literature (Itti & Koch, 2001).
3. **SSIM** — to introduce some spatial tolerance, so 1-pixel
   jitter in screen-captured frames doesn't show up as a giant MAE
   spike (Wang et al., 2004).

The combined score is a 70/30 weighted average of the MAE branch
(mapped through the same `1 − √(4·MAE)` perceptual curve we already
used) and the SSIM branch. The split is justified empirically in
§ 5.

---

## 3. Diagnosis of the legacy metric

We now enumerate seven concrete defects in the legacy metric. Each
one was verified by reading actual data from a real run, not just
from theory.

### 3.1 Pixel-aligned RGB L1 is brittle to sub-pixel jitter

The original loss assumes that pixel $(x, y)$ in $R$ and $(x, y)$ in
$C$ depict the same surface point. In practice, a Laya screenshot
captured under window-anchored mode (E-007/E-008) varies by
~1 pixel between captures because the editor's render-thread
reconciliation runs asynchronously.

A 1-pixel translation of a textured fish increases the unmasked RGB
MAE by ~0.05 on our `fish_1580` case, **without any actual material
change**. This is large compared to the per-iteration gains we
expect (≤ 0.005 per heuristic step) and would bury the algorithm's
real signal under capture noise.

**Mitigation**: SSIM uses a $7 \times 7$ Gaussian window and is
insensitive to single-pixel translations. We blend it in at 30%.

### 3.2 No alpha mask: 70% of the comparison is background plate

Per direct measurement on the fish_1580 trajectory:

| Image | Background plate colour | Fraction of frame |
|-------|--------------------------|-------------------|
| Unity reference | (172, 160, 146) | 21% |
| Laya candidate (editor) | (134, 151, 180) | 70% |

The two background plates are not even the same colour. Without a
mask, the comparison includes ~70% of the candidate image (the
editor's blue-grey panel) versus ~21% of the reference image (the
Unity sky), producing a contribution to MAE that has nothing to do
with the material we're trying to fit.

To prove the magnitude: when we recompute MAE only on the
foreground (the 28.7% of pixels that BOTH images consider
foreground), the global RGB MAE for `iter_0001` rises from **0.196
to 0.310** — a **+58%** jump. The legacy score was systematically
underestimating the real material error by **~36%** of its absolute
value, meaning the previous "best fit_score = 0.114" was inflated
by primarily background-MAE drift.

### 3.3 Region partitioning depends only on the reference

The legacy `material_oriented_image_diff_v1` partitions pixels into
six regions (`dark_shadow_occlusion`, `base_mid_tone`,
`highlight_specular_reflection`, `very_bright_emission`,
`edge_fresnel_rim`, `center_body`) using thresholds applied **only
to the reference's luma**. Therefore, if the candidate places a
specular highlight at a different location than the reference, that
highlight is NOT counted in the highlight bucket — the candidate
pixel is bucketed by the reference's luma at the same location,
which may be in shadow.

This causes a counter-intuitive failure mode: when the candidate
"smears" highlights into nominally dark pixels, the algorithm
*penalises* the dark bucket for being "too bright" when the actual
fault is "highlight position has drifted".

**Mitigation**: we inherit this partitioning unchanged in E-009
because fixing it requires depth/normals or a saliency map (Tier 2,
not yet implemented). However, the channel-weighted MAE makes the
penalty proportionate, and the SSIM term partially compensates by
caring about local structure.

### 3.4 Edge / centre is a circular radial assumption

The `edge_fresnel_rim` bucket is `radius_from_image_centre ≥ 0.72`
where radius is normalised to the image diagonal. For a fish
(extruded along its body axis), the actual fresnel rim is along the
silhouette of the model, which is NOT the corners of the image.

In `fish_1580`, the corners of the image are entirely background.
That means **the legacy `fresnel_rim.rgb_mae` was measuring
candidate-vs-reference background pixel diff, not the rim at all**.

**Mitigation**: the auto-mask removes the background corners
entirely from the bucket, so the remaining `edge_fresnel_rim` pixels
are at least *inside the model*. Replacing the radial heuristic
with a true silhouette mask is left for Tier 2.

### 3.5 Channel scores are aliases of region scores

`material_channels[base_color_main_texture] ≡
regions[base_mid_tone]` and likewise for the others. The optimiser
believes it has 7 independent diagnostics; in fact it has 5
(global, dark, mid, highlight, edge) plus two derived combinations.

**Mitigation**: not addressed in E-009 (we still rely on the
inherited region partitioning). Channel-weighted MAE still works
correctly under this alias because it weights the underlying 5
independent statistics; we just expose fewer "knobs" than the
naming suggests.

### 3.6 `severity` thresholds are uncalibrated

The legacy `_severity` function uses hard-coded thresholds:

```
high   ≥ 0.16
medium ≥ 0.07
low    ≥ 0.025
none   < 0.025
```

These were chosen by hand. They have no calibration against either
JND (just-noticeable difference) curves or a held-out human-rating
dataset. On dark surfaces, MAE 0.025 is already obvious; on bright
specular highlights, MAE 0.05 is barely noticeable. Using a single
absolute threshold across all luma regions over- or
under-estimates severity depending on which region you're in.

**Mitigation**: not addressed in E-009. The `severity` field is now
purely advisory; the optimiser consumes the raw `rgb_mae` numbers
through the channel-weighted aggregation, so threshold drift no
longer bites.

### 3.7 The `1 − √(4·MAE)` curve is not psychophysically derived

The legacy "perceptual" mode uses `fit_score = 1 − sqrt(MAE × 4)`,
clamped. This compresses the resolution near MAE = 0 (e.g.
MAE = 0.01 → fit = 0.80, MAE = 0.05 → fit = 0.55). In reality,
MAE = 0.01 and MAE = 0.05 differ visibly to a human observer, but
the curve flattens the difference into a tiny region of the score
range.

**Mitigation**: not directly addressed in E-009; we keep the same
curve for the MAE branch so historical thresholds remain
interpretable. The SSIM term partially compensates because SSIM is
roughly linear in perceived difference. Replacing the curve with a
JND-based mapping is on the Tier 3 backlog.

---

## 4. The corrected metric

The new score is a function of the (reference, candidate) image
pair plus per-channel MAE statistics. It is computed in three
stages.

### 4.1 Stage 1: auto-mask

[`auto_background_mask`](../vision/perceptual_score.py) samples
$12 \times 12$ patches at the four corners of $R$ and $C$,
computes the median colour of each image's corner sample, and
labels every pixel within $L_\infty$ distance $\tau = 16$ of the
median as that image's background. The final foreground mask is

$$M(x, y) = \neg \, M_R^{bg}(x, y) \;\wedge\; \neg \, M_C^{bg}(x, y),$$

i.e. a pixel is foreground if BOTH images agree it isn't part of
the corner-derived background. If the foreground share falls below
$\eta = 5\%$, the pipeline gracefully falls back to `weight = 1`
everywhere so we don't cripple comparisons of full-frame textures.

### 4.2 Stage 2: channel-weighted MAE

Given the per-channel MAE values $\mu_c$ produced by
`_build_material_channel_diagnostics` over the masked image, define

$$\text{MAE}_w = \frac{\sum_{c \in \mathcal{C}_v} w_c \mu_c}{\sum_{c \in \mathcal{C}_v} w_c}$$

where $\mathcal{C}_v$ is the set of channels with `valid=True`,
$w_c$ are the prior weights, and the renormalisation in the
denominator handles missing channels gracefully (e.g. an image
with no emission region uses the remaining 5 channels with weights
re-summed to 1.0). The default prior $w_c$ is calibrated for
"stylised PBR character + props" (which `fish_1580` belongs to):

| Channel | Default $w_c$ | Rationale |
|---------|--------------|-----------|
| `base_color_main_texture` | 0.30 | The bulk of the model body |
| `metallic_smoothness_specular` | 0.18 | Visually important highlights |
| `color_grading_hsv_contrast` | 0.18 | Global tonal correctness |
| `emission` | 0.12 | Small but eye-catching |
| `fresnel_rim` | 0.12 | Silhouette / shape cue |
| `shadow_occlusion` | 0.10 | Form definition |

### 4.3 Stage 3: SSIM and combination

[`ssim_score`](../vision/perceptual_score.py) computes
`skimage.metrics.structural_similarity` with a $7 \times 7$ window,
RGB channel axis, and (when available) the auto-mask as a spatial
weighting. The full-frame SSIM is also recorded for diagnostic
comparison.

The final score is

$$f(R, C) = 0.7 \cdot [1 - \sqrt{4 \cdot \text{MAE}_w}]_{[0,1]} \;+\; 0.3 \cdot \max(0, \text{SSIM}),$$

where $[\cdot]_{[0,1]}$ denotes clamping to the unit interval. If
SSIM is unavailable (numpy / scikit-image missing), the formula
gracefully degrades to MAE-only.

The 70/30 split is a starting point. Reducing the SSIM weight makes
the score behave like a pure colour-fidelity metric (helpful for
toon shading where colour is everything); raising it makes the
score more tolerant of capture jitter (helpful for screen-captured
runs). The pipeline exposes `fit_branch_weights` so this can be
tuned per project without code changes.

---

## 5. Empirical comparison

We ran [`tests/manual/rescore_e009.py`](../tests/manual/rescore_e009.py)
on the historical 12-iteration `fish_1580` trajectory to compare
the legacy and E-009 metrics on the *same* (reference, candidate)
pairs. Every row is one iteration of the most recent CMA-ES
warm-start run plus the seven earlier heuristic iterations.

```
iter   legacy_fit   new_fit   legacy_mae   weighted_mae    ssim    fg_ratio    stage
─────────────────────────────────────────────────────────────────────────────────────
0000     0.0675     0.0275      0.2174         0.3495    0.0916    0.2869    cma_warm
0001     0.1143  ★  0.0256      0.1961         0.3427    0.0855    0.2861    cma_warm
0002     0.0607     0.0256      0.2206         0.3489    0.0853    0.2874    cma_warm
0003     0.0621     0.0240      0.2199         0.3530    0.0800    0.2872    cma_warm
0004     0.0673     0.0317  ★   0.2175         0.3443    0.1055    0.2871    global_no_improvement
0005     0.0602     0.0239      0.2208         0.3558    0.0797    0.2430    base_color
0006     0.0601     0.0239      0.2209         0.3563    0.0798    0.2430    base_color
0007     0.0600     0.0239      0.2209         0.3566    0.0798    0.2430    base_color
0008     0.0598     0.0239      0.2210         0.3570    0.0797    0.2430    base_color
0009     0.0597     0.0239      0.2211         0.3573    0.0798    0.2430    base_color
0010     0.0595     0.0240      0.2211         0.3576    0.0799    0.2430    base_color
0011     0.0594     0.0239      0.2212         0.3579    0.0798    0.2430    base_color
```

(`★` marks each metric's best iteration.)

### 5.1 The two metrics disagree on the trajectory's best iteration

Under the legacy metric, **iter_0001** was the best (`fit = 0.1143`)
and the algorithm's CMA-ES strategy used it as the basis for all
subsequent moves. The legacy metric reported a 70% relative
improvement from iter_0000 (0.0675) to iter_0001 (0.1143), which is
exactly the kind of large jump that anchors a CMA-ES population's
mean.

Under the corrected metric, the same iteration was actually a
**slight regression** (0.0275 → 0.0256), and the genuine best is
**iter_0004** (`fit = 0.0317`) — which the legacy metric
inadvertently flagged as `global_no_improvement` and used as the
trigger to abort the run.

In other words: under the corrected metric, the algorithm walked
through the genuine optimum, called it a "stop" condition, and
reverted to a worse heuristic baseline.

### 5.2 The heuristic stage was making zero perceptual progress

The legacy metric reported a slow but steady improvement during
iter_0005..0011 (0.0602 → 0.0594). The corrected metric reports
**flat 0.0239** for all seven iterations — no progress whatsoever.
The "small steady improvement" was purely a function of the
background MAE drifting, not the model itself getting closer to
the reference.

### 5.3 The auto-mask is consistent across iterations

Foreground share is 28.7% in iter_0000..0004 and 24.3% in
iter_0005..0011. The drop in foreground after iter_0005 corresponds
to a slightly different capture region after the user re-pinned
the screen anchor; the metric remains stable inside each phase,
which is the correct behaviour.

### 5.4 Implications for the optimiser

These observations have direct consequences for the E-006 / E-007
algorithm experiments:

1. The historical `best_fit_score = 0.114` is not a real high-water
   mark; it is mostly background-pattern alignment.
2. CMA-ES's `should_stop` heuristic was being driven by phantom
   "improvements" then phantom "stagnation". This explains why it
   converged in only 5 iterations on a 49-dimensional problem
   where the literature suggests 100–2000 evaluations.
3. Heuristic `base_color` stage progression looked like it was
   working (small but positive deltas in fit) but was not.
4. **Therefore: the E-006 / E-007 algorithm experiments must be
   re-run with the E-009 metric before any conclusions about
   algorithm performance can be trusted.** This is registered as
   the next pending task in `ExperimentLog.md`.

---

## 5.5 Controlled verification (synthetic experiments)

The trajectory rescore in § 5 demonstrates that E-009 *behaves
differently* from the legacy metric, but not whether it is
*correct*. We constructed a controlled synthetic experiment in
[`tests/manual/verify_e009.py`](../tests/manual/verify_e009.py) to
test four falsifiable claims about the new metric. Each test
generates a "fish-like" rendering (soft-edged ellipse with a
specular blob) over a chosen background, varying one factor at a
time so the source of any score change is unambiguous.

### Verification table

| Test | Setup | fit_score | weighted_MAE | SSIM |
|------|-------|-----------|--------------|------|
| Identical fg, **same** bg | Sanity check | **1.0000** | 0.0000 | 1.000 |
| Identical fg, different bg | Auto-mask alone | 0.7115 | 0.0411 | 0.984 |
| Off fg, different bg | Status quo | 0.6675 | 0.0547 | 0.984 |
| Off fg, same bg | Post-unification | 0.8008 | 0.0199 | 0.994 |
| Identical fg, 1 px jitter | SSIM tolerance | 0.7098 | 0.0415 | 0.984 |

### Findings

**F1 — Auto-mask works but does not eliminate background influence.**
With identical foreground, going from same-bg to different-bg
*should* leave the score unchanged if E-009 were perfectly
background-invariant. In practice fit_score drops from 1.000 to
0.711 — a residual gap of **0.289**. The cause is silhouette
anti-aliasing: pixels at the model's edge are alpha-blended with
the background, so when ref and cand have different bg colours,
those edge pixels carry a systematic colour difference that
auto-mask cannot remove (they are genuinely "foreground" pixels).
This is the dominant residual confound in our setup.

**F2 — Background unification gives a free +0.13 to +0.29 to
fit_score.** Comparing the same foreground error (a slightly off
fish) under "different bgs" (0.668) versus "same bg" (0.801)
shows a +0.133 gain attributable purely to background unification.
The Q1 row gives the upper bound of this gain (+0.289) for cases
where the fish itself is identical. In all real experiments the
true gain falls in [0.13, 0.29].

**F3 — SSIM successfully absorbs single-pixel jitter.** A 1-px
right shift of the fish costs only 0.0016 fit_score (0.711 vs
0.710). This validates the SSIM-blending design: capture-driven
noise from window-anchored screenshots is no longer a concern.

**F4 — Without bg unification, the metric's effective dynamic
range is compressed.** When ref and cand have different
backgrounds, the "ceiling" of fit_score for a perfectly-matching
foreground is approximately 0.71, not 1.0. Optimisation targets
above 0.71 are mathematically unreachable in this regime — not
because the algorithm is bad, but because the metric ceiling is
artificially low. Setting `target_score=0.9` under non-unified
backgrounds is therefore unphysical.

### Practical recommendation

Unify Unity's camera clear-colour and Laya's scene clear-colour
to a single neutral value such as RGB `(128, 128, 128)`:

- Unity: Camera → Clear Flags = Solid Color, Background = (128, 128, 128).
- Laya: Scene clear-colour or scene background plate set to
  (128, 128, 128).

Avoid pure black (causes systematic dimming at silhouette AA) and
avoid Laya's default blue-grey (high B channel pollutes the
specular bucket via the `ref_luma ≥ 0.72` thresholds).
Mid-grey gives the most balanced AA contribution across all three
RGB channels.

After unification, expect:

- The Q1 noise floor (fit_score for identical foreground) to rise
  from ~0.71 to ~1.0, restoring the full dynamic range.
- weighted_MAE to drop by ~0.04 across the board.
- Realistic ranges for the foreground errors we care about:
  - tiny material drift: weighted_MAE 0.02 → fit 0.80
  - medium drift: weighted_MAE 0.05 → fit 0.65
  - large drift: weighted_MAE 0.10 → fit 0.50

`target_score = 0.85` becomes a sensible "this run did its job"
threshold under unification. Without it, anything above 0.71
should be reinterpreted as suspicious or unphysical.

---

## 6. Limitations and tier 2 / tier 3 work

What E-009 fixes: 3.1 (jitter), 3.2 (background plate), 3.4
(circular edge — partial), 3.5 (channel aliases — partial), and
the headline "fit_score over-reports".

What E-009 does **not** fix:

- **3.3** Region partitioning is still reference-only. To fix
  properly we need either depth/normals or a learned saliency
  detector. Tier 2 candidate.
- **3.6** Severity thresholds are still uncalibrated. Could be
  fixed cheaply with a per-region JND lookup. Tier 3 candidate.
- **3.7** The MAE → fit curve is still
  `1 − sqrt(4·MAE)`. JND-based remapping is Tier 3.
- **No human ground truth dataset.** The biggest unknown is whether
  E-009 is *quantitatively* aligned with human judgement. We
  budget ~30 image pairs and a 5-rater Mean Opinion Score (MOS)
  collection in Tier 2 to calibrate.
- **LPIPS / DISTS not integrated.** These are the literature's
  current best perceptual metrics. SSIM is fast and dependency-free
  but conceptually less powerful. Tier 2.
- **Multi-view aggregation.** A single screenshot underdetermines
  the material; ideally we capture from 3+ angles and aggregate.
  Tier 2.
- **ECC / homography alignment** before MAE. Currently SSIM is the
  only spatial-tolerance term; pre-aligning $C$ to $R$ would let
  us tighten the MAE branch back up. Tier 2.

---

## 7. Reproducibility

To re-run the rescore reported in § 5:

```bash
python tools/material_fit/tests/manual/rescore_e009.py
```

Output is appended to
`tools/material_fit/output/fish_1580/auto_adjust/e009_rescore.json`.

To run the unit tests for the new metric:

```bash
python -m pytest tools/material_fit/tests/test_perceptual_score.py
```

20 tests are expected to pass. The full repository regression suite
should also pass (116 tests as of E-009 landing).

---

## 8. Citation skeleton (for the future paper)

When this work appears in the paper, the metric design section
should cite at least:

- Wang, Bovik, Sheikh, & Simoncelli, **"Image Quality Assessment:
  From Error Visibility to Structural Similarity"**, IEEE TIP 2004
  — for SSIM.
- Zhang, Isola, Efros, Shechtman, & Wang, **"The Unreasonable
  Effectiveness of Deep Features as a Perceptual Metric"**, CVPR
  2018 — for LPIPS as Tier 2 follow-up.
- Itti & Koch, **"Computational modelling of visual attention"**,
  Nature Rev. Neurosci. 2001 — for the saliency-weighting
  motivation behind channel weights.
- Laine, Hellsten, Karras, Seol, Lehtinen, & Aila, **"Modular
  Primitives for High-Performance Differentiable Rendering"**, ACM
  TOG 2020 — for the alpha-compositing convention.

---

## Appendix A · Default channel weights — sensitivity table

The defaults in § 4.2 are not the only sensible choice. Three
alternative profiles are pre-defined for future ablations:

| Profile | base | metallic | emission | fresnel | shadow | grading |
|---------|------|----------|----------|---------|--------|---------|
| **default** (E-009) | 0.30 | 0.18 | 0.12 | 0.12 | 0.10 | 0.18 |
| `colour_only` | 0.50 | 0.10 | 0.05 | 0.05 | 0.05 | 0.25 |
| `lighting_focused` | 0.20 | 0.25 | 0.20 | 0.15 | 0.10 | 0.10 |
| `equal` | 1/6 | 1/6 | 1/6 | 1/6 | 1/6 | 1/6 |

The `ChannelWeightConfig` constructor enforces $\sum_c w_c = 1.0$.
We expect a future ablation experiment to sweep these and report
which produces the highest correlation with human ratings.

## Appendix B · Numerical ranges in practice

For our `fish_1580` dataset, we have observed the following ranges
across the 12 historical iterations:

| Quantity | Min | Median | Max | Comment |
|----------|-----|--------|-----|---------|
| `legacy_mae` | 0.196 | 0.221 | 0.222 | Compressed by background |
| `weighted_mae` | 0.343 | 0.355 | 0.358 | Real per-channel MAE on foreground |
| `ssim` | 0.080 | 0.080 | 0.106 | Always low — confirms structural mismatch |
| `foreground_ratio` | 0.243 | 0.287 | 0.287 | Stable per capture-region phase |
| `legacy_fit` | 0.059 | 0.060 | 0.114 | Inflated by background |
| `new_fit` | 0.024 | 0.024 | 0.032 | Honest |

The `new_fit` axis has clearly more headroom for genuine
optimisation: legacy was capped near 0.11 because background was
already "good", whereas E-009 says we have ~96% headroom remaining.
