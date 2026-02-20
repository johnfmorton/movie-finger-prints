# Changelog

## [Unreleased]

### Fixed
- Cell Aspect Ratio UI (From video, 16:9, 4:3, 1:1, Custom) now connected to the generation pipeline
- Frames are pre-cropped to the selected aspect ratio before fitting into cells, removing pillarboxing/letterboxing
- Works with both Standard and Quadtree grid modes

## [1.1.1] - 2026-02-20

### Fixed
- ffmpeg/ffprobe not found when running as macOS .app bundle due to missing PATH

## [1.1.0] - 2026-02-20

### Added
- Visual frame picker dialog for browsing video and selecting highlight timestamps
- Thumbnail overview strip with ~20 evenly-spaced frames for quick navigation
- Large frame preview with timeline slider and 200ms debounce
- Frame-step buttons for fine-grained control (1, 10, 30 frames forward/back)
- Keyboard navigation: Arrow keys step 1 frame, Option+Arrow steps 10 frames
- Help text labels in frame picker explaining each section
- Highlight frames feature for featuring key moments in largest quadtree cells
- "Pick Frames..." button in Highlight Frames group

## 1.0.0 - 2026-02-18

### Added
- GUI application for generating movie fingerprints from video files
- Grid and quadtree layout modes with recursive subdivision
- Multiple fill orders (row, column, spiral, diagonal, random)
- Custom styling options (gap size, border radius, background color)
- Output format support (PNG, JPEG, WebP)
- Grid preview for visualizing layout before processing
- macOS .app bundle via PyInstaller

[Unreleased]: https://github.com/johnfmorton/movie-finger-prints/compare/v1.1.1...HEAD
[1.1.1]: https://github.com/johnfmorton/movie-finger-prints/releases/tag/v1.1.1
[1.1.0]: https://github.com/johnfmorton/movie-finger-prints/releases/tag/v1.1.0
