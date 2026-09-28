import 'package:flutter/material.dart';

/// 九套氛围主题，与桌面端 data-theme 一一对应：
/// 暗 6（烛光手稿/雾夜/琥珀/月下钟楼/烬火余温）+ 亮 3（纸页/晨光/青原/糖霜）。
enum AppTheme {
  candle,
  fog,
  paper,
  amber,
  mystery,
  dungeon,
  dawn,
  meadow,
  blush,
}

ColorScheme _schemeFor(AppTheme theme) => switch (theme) {
  AppTheme.candle => const ColorScheme.dark(
    primary: Color(0xffe2a558),
    surface: Color(0xff1c1510),
    onSurface: Color(0xffe8dcc4),
  ),
  AppTheme.fog => const ColorScheme.dark(
    primary: Color(0xffd7af67),
    surface: Color(0xff10211f),
    onSurface: Color(0xffedf0e7),
  ),
  AppTheme.paper => const ColorScheme.light(
    primary: Color(0xff2d6b59),
    surface: Color(0xfff2eee5),
    onSurface: Color(0xff1e312b),
  ),
  AppTheme.amber => const ColorScheme.dark(
    primary: Color(0xffe5a85f),
    surface: Color(0xff281d16),
    onSurface: Color(0xfffff4e8),
  ),
  AppTheme.mystery => const ColorScheme.dark(
    primary: Color(0xffa9c3b8),
    surface: Color(0xff101820),
    onSurface: Color(0xffdde5e2),
  ),
  AppTheme.dungeon => const ColorScheme.dark(
    primary: Color(0xffd4743c),
    surface: Color(0xff170e09),
    onSurface: Color(0xffecdcc8),
  ),
  AppTheme.dawn => const ColorScheme.light(
    primary: Color(0xffbd7f2e),
    surface: Color(0xfff2e9d8),
    onSurface: Color(0xff3a2f22),
  ),
  AppTheme.meadow => const ColorScheme.light(
    primary: Color(0xff3f8a64),
    surface: Color(0xffedf3ec),
    onSurface: Color(0xff26332b),
  ),
  AppTheme.blush => const ColorScheme.light(
    primary: Color(0xffc96a8a),
    surface: Color(0xfff8eef1),
    onSurface: Color(0xff3d2a33),
  ),
};

ThemeData themeDataFor(AppTheme theme) {
  final scheme = _schemeFor(theme);
  return ThemeData(
    colorScheme: scheme,
    scaffoldBackgroundColor: scheme.surface,
    useMaterial3: true,
    cardTheme: CardThemeData(color: scheme.surfaceContainerHighest),
    inputDecorationTheme: const InputDecorationTheme(
      border: OutlineInputBorder(),
    ),
  );
}
