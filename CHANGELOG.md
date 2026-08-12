# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Windows portable package (PyInstaller onedir) with double-click connection
  launcher, bilingual interface, and third-party license bundle
- PySide6 vision workbench as the default PC client (Original / Gray / Canny /
  HSV / Contours), replacing Tkinter as the default entry point
- Qt / PySide6 LGPL-3.0 compliance documentation and license texts
- Open-source collaboration docs: contributing guide, security policy, support
  guide, roadmap, issue/PR templates

## [0.1.0-alpha.1] - unreleased

> Version line reserved for the first tagged pre-release. Dates are added when a
> tag is cut; no dates are fabricated here.

### Added

- Android sensor app: Camera2 preview + ImageReader(JPEG) + NanoHTTPD MJPEG server
  (`GET /ping`, `GET /stream`)
- PC client: strict MJPEG parser, OpenCV vision modes, PySide6 workbench
  (bilingual zh-CN/en), legacy Tkinter client kept for compatibility
- Fully local operation — no cloud, no account, no telemetry

> Repository URL (once public) is added to the version-links section at release
> time.
