# Demo and thesis materials

Large demo and thesis assets are not stored in normal Git history. The local folder `ThesisDocsAndVideo/` is ignored because it contains Office documents and MP4 recordings that are better distributed as release assets or external video links.

The technical content from those assets is summarized in [Thesis overview](../thesis/README.md). This keeps the repository useful for readers without committing large `.docx`, `.pptx`, or `.mp4` files.

## Recommended publishing flow

1. Export or upload final demo videos to GitHub Releases, YouTube, Vimeo, or another stable public location.
2. Add the public URLs below.
3. Keep only small screenshots, thumbnails, or SVG/PNG diagrams in `docs/assets/`.

## Release asset inventory

Update these links after creating a GitHub Release:

| Asset | Suggested public name | Link |
| --- | --- | --- |
| Full demo video | `demo-full.mp4` | TODO: add release/video URL |
| Admin workflow video | `admin-flow.mp4` | TODO: add release/video URL |
| Phase 1 video | `phase-1.mp4` | TODO: add release/video URL |
| Phase 3 video | `phase-3.mp4` | TODO: add release/video URL |
| Phase 4 video | `phase-4.mp4` | TODO: add release/video URL |
| Meal day workflow video | `meal-day.mp4` | TODO: add release/video URL |
| Thesis document | `thesis.docx` or `thesis.pdf` | TODO: add release URL |
| Thesis slides | `thesis-slides.pptx` | TODO: add release URL |

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
