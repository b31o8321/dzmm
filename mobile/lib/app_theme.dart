import 'package:flutter/material.dart';

enum AppTheme { fog, paper, amber }

ThemeData themeDataFor(AppTheme theme) {
  final scheme = switch (theme) {
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
  };
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
