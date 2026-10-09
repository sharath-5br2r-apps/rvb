# AdvancedStore

A fast, modern, and clean catalog for patched Android applications, desktop builds, and Magisk/KernelSU modules built across multiple automated repositories.

[![Website](https://img.shields.io/badge/Store-Website-21a378?style=flat&logo=homeassistantcommunitystore&logoColor=white)](https://sharath-5br2r.github.io/apps)
[![GitHub Stars](https://img.shields.io/github/stars/sharath-5br2r/apps?label=Stars&logo=github&style=social)](https://github.com/sharath-5br2r/apps)
[![Discussions](https://img.shields.io/badge/Discussions-Join-blue?style=flat&logo=github&logoColor=white)](https://github.com/sharath-5br2r/apps/discussions)
[![Website Visitors](https://visitor-badge.laobi.icu/badge?page_id=sharath-5br2r.github.io.apps&left_text=Website%20Visitors&right_color=%231283c3&format=true&query_only=true)](https://sharath-5br2r.github.io/apps)

---

## ✨ Features & Enhancements

### 📦 Multi-Repository Aggregation
- **Unified Catalog**: Automatically aggregates, merges, and presents builds across multiple automated repositories into a single responsive frontend:
  - [`apps`](https://github.com/sharath-5br2r/apps): Core ReVanced & Morphe patched applications.
  - [`Eden-Workflow`](https://github.com/sharath-5br2r/Eden-Workflow): Eden Android and PC/Desktop builds.
  - [`Dolphin-Extra`](https://github.com/sharath-5br2r/Dolphin-Extra): Custom Dolphin emulator forks and enhancements.
  - [`LeviLaunchroid-Extra`](https://github.com/sharath-5br2r/LeviLaunchroid-Extra): Specialized launcher builds.
  - [`ZalithLauncher2-Extra`](https://github.com/sharath-5br2r/ZalithLauncher2-Extra): ZalithLauncher2 workflow releases.
- **Automated Workflow Pipeline**: GitHub Actions periodically rebuild and deduplicate catalog data using Schema v2, with zero-downtime deployment to GitHub Pages.

### 🔍 Advanced Filter Toolbar & In-Memory Search
- **Multi-Facet Dropdown Filtering**: Filter builds seamlessly across:
  - **Repository**: View all or isolate specific upstream build workflows.
  - **Patch Engine**: Filter by ReVanced, Morphe, LSPatch, NPatch, etc.
  - **Patch Sources / Authors**: Filter by individual patch creators (Anddea, Piko, Inotia00, etc.).
  - **Operating System / Platform**: Filter by Android, Windows, Linux, or macOS.
  - **Sorting**: Sort dynamically by Recently Updated, Most Popular (total downloads), or Name (A-Z).
- **Categorized Chip Navigation**: Filter by app genres (Browsers, Emulator, Games, Launchers, Media/Video, Productivity, Social, Utilities, VPN).
- **Instant Search**: Real-time weighted search indexing app names, package IDs, patch engines, variants, and architectures.

### 📲 Seamless Obtainium / ObtainX Integration
- **One-Click Setup**: Generate direct `obtainium://app/...` import links for instant tracking and automatic in-app updates.
- **Accurate Variant & Subvariant Targeting**: Regex-based asset matching tuned per package and architecture (including clone builds, Android TV variants, and specific compiler targets).
- **Interactive Setup Instructions**: In-modal step-by-step guidance for configuring Obtainium.

### 🎨 Modern UI & Customization
- **Theme Modes**: Support for System, Dark, and Light appearance modes.
- **Theme Styles**: Switch between Zen (minimalist) and Material 3 design styles.
- **System Font Toggle**: Choose between modern typography (Bricolage Grotesque & Geist Mono) or native system fonts.
- **Detailed Build Modals**:
  - Modal breakdown of stable vs. beta releases with direct download links.
  - Architecture-specific grouping (ARM64-v8a, ARMv7a, x86_64, Universal).
  - Applied patches checklist and formatted markdown changelog viewer.
- **Troubleshooting & Diagnostics**: Integrated quick-clear cache utility, issue report links for each source repo, and discussion board shortcuts.

---

<details>
<summary><strong>📖 NullStore Original Readme</strong></summary>

<br>

<div align="center"><a href="https://github.com/Safouene1/support-palestine-banner/blob/master/Markdown-pages/Support.md"><img src="https://raw.githubusercontent.com/Safouene1/support-palestine-banner/master/banner-support.svg" alt="Support Palestine" style="width: 100%;"></a></div>

[![NullStore social preview](social-preview.svg)](https://nullcpy.github.io/)

<p align="center"><a href="https://t.me/rvb27"><img src="https://img.shields.io/badge/Group-26A5E4?style=flat&logo=telegram&logoColor=white"></a> <a href="https://nullcpy.github.io/"><img src="https://img.shields.io/badge/Store-21a378?style=flat&logo=homeassistantcommunitystore&logoColor=white"></a> <a href="https://t.me/s/rvb28"><img src="https://img.shields.io/badge/Channel-26A5E4?style=flat&logo=telegram&logoColor=white"></a> <a href="https://fahim-ahmed05.github.io/donate"><img src="https://img.shields.io/badge/Donate-ea4335?style=flat&logo=ko-fi&logoColor=white"></p>

<p align="center"><a href="https://github.com/nullcpy/nullcpy.github.io"><img src="https://img.shields.io/github/stars/nullcpy/nullcpy.github.io?label=Website%20Stars&logo=github&style=social"></a> <a href="https://github.com/nullcpy/rvb"><img src="https://img.shields.io/github/stars/nullcpy/rvb?label=Builder%20Stars&logo=github&style=social"></a></p>

<p align="center"><a href="https://nullcpy.github.io"><img src="https://visitor-badge.laobi.icu/badge?page_id=nullcpy.github.io&left_text=Website%20Visitors&right_color=%231283c3&format=true&query_only=true"></a> <a href="https://github.com/nullcpy/rvb"><img src="https://visitor-badge.laobi.icu/badge?page_id=nullcpy.rvb&left_text=GitHub%20Visitors&format=true"></a> </p>

<p align="center"><a href="https://github.com/nullcpy/rvb/issues/new/choose"><img src="https://img.shields.io/badge/Report%20/%20Request-405771?style=flat&logo=github" alt="Report issues or request features"></a></p>

---

<p align="center"><a href="https://github.com/nullcpy/rvb/issues"><img src="https://img.shields.io/badge/Issues-2f2f2f?style=flat&logo=github&logoColor=white"></a> <a href="https://github.com/nullcpy/nullcpy.github.io/pulls"><img src="https://img.shields.io/badge/Pull%20Requests-2f2f2f?style=flat&logo=github&logoColor=white"></a> <a href="https://github.com/nullcpy/rvb/discussions"><img src="https://img.shields.io/badge/Discussions-2f2f2f?style=flat&logo=github&logoColor=white"></a> <a href="https://github.com/nullcpy/nullcpy.github.io/actions"><img src="https://img.shields.io/badge/Actions-2f2f2f?style=flat&logo=github&logoColor=white"></a></p>

---

## 🤝 Support the Project

Building, testing, and maintaining these automated workflows takes a significant amount of time. If this builder has saved you time or made your life easier, any support is hugely appreciated!

- **❤️ [Donate](https://fahim-ahmed05.github.io/donate)** if you can.
- **⭐ Star this repository** (This is a huge help!)
- **📢 Share the project** with others who might find it useful.

Thank you to everyone who helps keep this project alive!

</details>
