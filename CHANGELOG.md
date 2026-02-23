# Changelog

## [Unreleased]

## [1.2.0] - 2026-02-23

### Added
- Two-column layout with scrollable area for small-screen fallback
- Collapsible sections replacing group boxes for a cleaner UI
- Modern light theme via QSS stylesheet (white cards, blue accent, styled inputs)
- Physics grid mode with pymunk collision simulation
- Per-key-frame emphasis styles in standard grid mode
- Custom spin box arrow icons for better visibility

### Changed
- Minimum window width increased to 950px with 1050x750 default size
- Generate button styled as primary action (blue)
- Frame picker dialog minimum height increased for better layout

### Fixed
- Cell Aspect Ratio UI now connected to the generation pipeline
- Frames are pre-cropped to the selected aspect ratio before fitting into cells
- Frame preview no longer overlaps slider and step buttons in picker dialog
- Frame picker thumbnails and help text updated for light theme consistency

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

[Unreleased]: https://github.com/johnfmorton/movie-finger-prints/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/johnfmorton/movie-finger-prints/releases/tag/v1.2.0
[1.1.1]: https://github.com/johnfmorton/movie-finger-prints/releases/tag/v1.1.1
[1.1.0]: https://github.com/johnfmorton/movie-finger-prints/releases/tag/v1.1.0
