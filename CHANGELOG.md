# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Basic test structure and test files

## [1.0.0] - 2025-06-30

### Added
- Initial release of ESP32 Writer system
- USB memory detection and automatic sketch loading
- Arduino CLI integration for building sketches
- esptool.py integration for flashing ESP32 devices
- 4-LED status indication system (Red=Error, Green=Ready, Orange=Processing, Blue=Complete)
- OLED/TFT display support for progress visualization
- Hardware button control interface
- Multiple sketch selection functionality
- USB Mass Storage gadget functionality
- External library auto-installation support
- Direct binary file flashing support
- Comprehensive logging system
- Configuration files for boards and UI settings
- systemd service integration
- Installation and setup scripts

### Features
- Supports ESP32 and ESP32-S3 boards
- Automatic board type detection from sketch files
- Priority-based sketch sorting (newer .ino files prioritized)
- Read-only protection during flashing operations
- Graceful error handling and recovery
- Modular architecture with clear separation of concerns

### Hardware Support
- Raspberry Pi Zero 2 W
- Raspberry Pi 4 Model B
- I2C OLED displays (SSD1306)
- SPI TFT displays (ILI9341)
- HDMI display output
- USB-Serial converters (CP2102/CH340)

[1.0.0]: https://github.com/RooLab/esp32-writer/releases/tag/v1.0.0
