# Demo and thesis materials

Large thesis Office assets are not stored in normal Git history. Demo MP4 recordings that are useful for public readers are copied into `docs/assets/videos/` so GitHub can render or link them directly.

The technical content from those assets is summarized in [Thesis overview](../thesis/README.md). This keeps the repository useful for readers without committing large `.docx`, `.pptx`, or `.mp4` files.

## Recommended publishing flow

1. Keep source thesis Office files (`.docx`, `.pptx`) outside Git history.
2. Keep public MP4 demos in `docs/assets/videos/` with stable lowercase names.
3. If video size becomes a problem, move the MP4 files to GitHub Releases and replace the links below.

## Release asset inventory

Update these links after creating a GitHub Release:

| Asset | Suggested public name | Link |
| --- | --- | --- |
| Full demo video | `demo-full.mp4` | [Open](../assets/videos/demo-full.mp4) |
| Admin workflow video | `admin-flow.mp4` | [Open](../assets/videos/admin-flow.mp4) |
| Phase 1 video | `phase-1.mp4` | [Open](../assets/videos/phase-1.mp4) |
| Phase 3 video | `phase-3.mp4` | [Open](../assets/videos/phase-3.mp4) |
| Phase 4 video | `phase-4.mp4` | [Open](../assets/videos/phase-4.mp4) |
| Meal day workflow video | `meal-day.mp4` | [Open](../assets/videos/meal-day.mp4) |
| Week plan workflow video | `week-plan.mp4` | [Open](../assets/videos/week-plan.mp4) |
| Thesis document | `thesis.docx` or `thesis.pdf` | TODO: add release URL |
| Thesis slides | `thesis-slides.pptx` | TODO: add release URL |

## Embedded preview

<video src="../assets/videos/demo-full.mp4" controls width="100%"></video>

## Local demo recordings

The ignored `ThesisDocsAndVideo/` folder currently contains these recordings. Upload them to GitHub Releases or a video platform, then replace the TODO links above.

| Local filename | Size | Public description |
| --- | ---: | --- |
| `Demo.mp4` | ~56.7 MB | Full end-to-end system demonstration |
| `admin.mp4` | ~9.5 MB | Admin/review workflow |
| `Phase1.mp4` | ~8.0 MB | Initial setup/profile/configuration flow |
| `phase 3.mp4` | ~14.0 MB | Intermediate MealAgent feature flow |
| `phase 4.mp4` | ~7.1 MB | Final integration/evaluation flow |
| `meal day.mp4` | ~7.9 MB | Daily meal-planning workflow |
| `week plan.mp4` | ~5.4 MB | Weekly meal-planning workflow |

## Diagram guidance

If diagrams from `ThesisDocsAndVideo/Diagrams/` are useful for the public README/docs, export lightweight final versions into `docs/assets/figures/` and reference those files instead of committing large editable bundles.
