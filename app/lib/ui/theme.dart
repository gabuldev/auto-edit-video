import 'package:flutter/material.dart';

/// The tokens of desktop/ui/styles.css (`:root`), so both apps look the same.
abstract final class Tokens {
  static const bg = Color(0xFF0D1015);
  static const panel = Color(0xFF151A22);
  static const panel2 = Color(0xFF12161E);
  static const sidebar = Color(0xFF121620);
  static const border = Color(0xFF232C38);
  static const borderSoft = Color(0xFF1E242E);
  static const text = Color(0xFFE7EBF2);
  static const dim = Color(0xFF9AA4B2);
  static const faint = Color(0xFF6B7484);
  static const accent = Color(0xFF2EE6C6);
  static const accentDeep = Color(0xFF1AA6D6);
  static const navActive = Color(0xFF1B2531);
  static const ok = Color(0xFF4ADE80);
  static const run = Color(0xFFF5B544);
  static const err = Color(0xFFF87171);
  static const info = Color(0xFF5B9DFF);

  static const font = 'SpaceGrotesk';
  static const mono = 'JetBrainsMono';
}

ThemeData buildTheme() {
  const scheme = ColorScheme.dark(
    primary: Tokens.accent,
    onPrimary: Color(0xFF06231F),
    secondary: Tokens.info,
    surface: Tokens.panel,
    onSurface: Tokens.text,
    error: Tokens.err,
    outline: Tokens.border,
    outlineVariant: Tokens.borderSoft,
  );
  final base = ThemeData(useMaterial3: true, colorScheme: scheme, fontFamily: Tokens.font);
  return base.copyWith(
    scaffoldBackgroundColor: Tokens.bg,
    dividerColor: Tokens.borderSoft,
    textTheme: base.textTheme.apply(bodyColor: Tokens.text, displayColor: Tokens.text),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: Tokens.accent,
        foregroundColor: const Color(0xFF06231F),
        textStyle: const TextStyle(fontFamily: Tokens.font, fontWeight: FontWeight.w600),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: Tokens.text,
        side: const BorderSide(color: Tokens.border),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      ),
    ),
  );
}

/// The gradient "G" square of the brand.
class BrandLogo extends StatelessWidget {
  const BrandLogo({super.key, this.size = 34});
  final double size;

  @override
  Widget build(BuildContext context) => Container(
    width: size,
    height: size,
    alignment: Alignment.center,
    decoration: BoxDecoration(
      borderRadius: BorderRadius.circular(size * 0.265),
      gradient: const LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [Tokens.accent, Tokens.accentDeep],
      ),
    ),
    child: Text(
      'G',
      style: TextStyle(fontWeight: FontWeight.w700, fontSize: size * 0.56, color: const Color(0xFF06231F)),
    ),
  );
}
